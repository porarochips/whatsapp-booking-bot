from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from pymongo import ASCENDING, MongoClient, ReturnDocument
from config import Config

_client: Optional[MongoClient] = None


def get_db():
    global _client
    if _client is None:
        if not Config.MONGO_URI:
            raise RuntimeError("MONGO_URI is not set in environment variables.")
        _client = MongoClient(Config.MONGO_URI)
        ensure_indexes(_client[Config.MONGO_DB_NAME])
    return _client[Config.MONGO_DB_NAME]


def ensure_indexes(db) -> None:
    db.businesses.create_index([("phone_number_id", ASCENDING)], unique=True)
    db.bookings.create_index(
        [("business_id", ASCENDING), ("date", ASCENDING), ("time", ASCENDING), ("status", ASCENDING)]
    )
    db.bookings.create_index([("business_id", ASCENDING), ("customer_phone", ASCENDING)])
    db.conversation_sessions.create_index(
        [("business_id", ASCENDING), ("customer_phone", ASCENDING)], unique=True
    )
    # Automatically expire stale draft sessions after SESSION_TTL_MINUTES
    db.conversation_sessions.create_index(
        [("updated_at", ASCENDING)], expireAfterSeconds=Config.SESSION_TTL_MINUTES * 60
    )


def get_business_by_phone_number_id(phone_number_id: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    return db.businesses.find_one({"phone_number_id": str(phone_number_id), "active": True})


def update_business_fields(business_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    db = get_db()
    return db.businesses.find_one_and_update(
        {"_id": business_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )


def add_closed_date(business_id: str, date_str: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    return db.businesses.find_one_and_update(
        {"_id": business_id},
        {"$addToSet": {"closed_dates": date_str}},
        return_document=ReturnDocument.AFTER,
    )


def remove_closed_date(business_id: str, date_str: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    return db.businesses.find_one_and_update(
        {"_id": business_id},
        {"$pull": {"closed_dates": date_str}},
        return_document=ReturnDocument.AFTER,
    )


def count_confirmed_bookings(business_id: str, date_str: str, time_str: str) -> int:
    db = get_db()
    return db.bookings.count_documents(
        {
            "business_id": business_id,
            "date": date_str,
            "time": time_str,
            "status": "confirmed",
        }
    )


def get_bookings_for_date(business_id: str, date_str: str) -> List[Dict[str, Any]]:
    db = get_db()
    cursor = db.bookings.find(
        {"business_id": business_id, "date": date_str, "status": "confirmed"}
    ).sort("time", ASCENDING)
    return list(cursor)


def create_booking_if_available(
    business: Dict[str, Any],
    date_str: str,
    time_str: str,
    customer_name: str,
    customer_phone: str,
    details: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Re-checks capacity right before inserting so concurrent requests
    cannot exceed business['slot_capacity'].
    """
    db = get_db()
    capacity = int(business.get("slot_capacity", 1))
    current_count = count_confirmed_bookings(business["_id"], date_str, time_str)
    if current_count >= capacity:
        return None

    doc = {
        "business_id": business["_id"],
        "date": date_str,
        "time": time_str,
        "customer_name": customer_name.strip(),
        "customer_phone": str(customer_phone).strip(),
        "details": details.strip() if details else None,
        "status": "confirmed",
        "created_at": datetime.now(timezone.utc),
    }
    result = db.bookings.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def cancel_booking_by_time_or_id(business_id: str, date_str: str, target: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    query = {
        "business_id": business_id,
        "date": date_str,
        "status": "confirmed",
        "$or": [{"time": target.strip()}, {"booking_code": target.strip().upper()}],
    }
    return db.bookings.find_one_and_update(
        query,
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )


def get_session(business_id: str, customer_phone: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    session = db.conversation_sessions.find_one(
        {"business_id": business_id, "customer_phone": str(customer_phone)}
    )
    if not session:
        return None
    updated_at = session.get("updated_at")
    if updated_at:
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - updated_at > timedelta(minutes=Config.SESSION_TTL_MINUTES):
            clear_session(business_id, customer_phone)
            return None
    return session


def upsert_session(business_id: str, customer_phone: str, draft: Dict[str, Any]) -> None:
    db = get_db()
    db.conversation_sessions.update_one(
        {"business_id": business_id, "customer_phone": str(customer_phone)},
        {
            "$set": {
                "draft": draft,
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )


def clear_session(business_id: str, customer_phone: str) -> None:
    db = get_db()
    db.conversation_sessions.delete_one(
        {"business_id": business_id, "customer_phone": str(customer_phone)}
    )