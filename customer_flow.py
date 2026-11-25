import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import pytz
from google import genai
from config import Config
from database import (
    clear_session,
    count_confirmed_bookings,
    create_booking_if_available,
    get_session,
    upsert_session,
)

_client: Optional[genai.Client] = None


def _get_gemini_client() -> Optional[genai.Client]:
    global _client
    if not Config.GEMINI_API_KEY:
        return None
    if _client is None:
        _client = genai.Client(api_key=Config.GEMINI_API_KEY)
    return _client


def _now_local(business: Dict[str, Any]) -> datetime:
    tz_name = business.get("timezone", "Africa/Harare")
    return datetime.now(pytz.timezone(tz_name))


def _generate_time_slots(business: Dict[str, Any]) -> List[str]:
    open_str = business.get("open_time", "08:00")
    close_str = business.get("close_time", "17:00")
    step_mins = int(business.get("slot_duration_mins", 60))

    start_dt = datetime.strptime(open_str, "%H:%M")
    end_dt = datetime.strptime(close_str, "%H:%M")

    slots: List[str] = []
    cur = start_dt
    while cur + timedelta(minutes=step_mins) <= end_dt:
        slots.append(cur.strftime("%H:%M"))
        cur += timedelta(minutes=step_mins)
    return slots


def _is_date_open(business: Dict[str, Any], date_str: str) -> Tuple[bool, str]:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return False, "invalid_date"

    today_str = _now_local(business).strftime("%Y-%m-%d")
    if date_str < today_str:
        return False, "past_date"

    closed_dates = set(business.get("closed_dates", []))
    if date_str in closed_dates:
        return False, "closed_date"

    working_days = set(business.get("working_days", [0, 1, 2, 3, 4, 5]))
    if dt.weekday() not in working_days:
        return False, "non_working_day"

    return True, "ok"


def _find_next_open_date(business: Dict[str, Any], start_from_str: str) -> Optional[str]:
    cur = datetime.strptime(start_from_str, "%Y-%m-%d") + timedelta(days=1)
    for _ in range(30):
        candidate = cur.strftime("%Y-%m-%d")
        is_open, _ = _is_date_open(business, candidate)
        if is_open:
            slots = _generate_time_slots(business)
            cap = int(business.get("slot_capacity", 1))
            if any(count_confirmed_bookings(business["_id"], candidate, s) < cap for s in slots):
                return candidate
        cur += timedelta(days=1)
    return None


def _find_alternative_slots(
    business: Dict[str, Any], date_str: str, preferred_time: Optional[str]
) -> Tuple[str, List[str]]:
    """
    Returns (target_date_str, list_of_available_HH_MM_slots).
    First checks slots on `date_str` (preferring times at/after `preferred_time` if given),
    otherwise falls back to the next open working day.
    """
    is_open, _ = _is_date_open(business, date_str)
    slots = _generate_time_slots(business)
    cap = int(business.get("slot_capacity", 1))

    if is_open:
        candidates = slots
        if preferred_time:
            later = [s for s in slots if s >= preferred_time]
            earlier = [s for s in slots if s < preferred_time]
            candidates = later + earlier
        available = [
            s for s in candidates if count_confirmed_bookings(business["_id"], date_str, s) < cap
        ]
        if available:
            return date_str, available[:3]

    next_date = _find_next_open_date(business, date_str)
    if next_date:
        next_avail = [
            s for s in slots if count_confirmed_bookings(business["_id"], next_date, s) < cap
        ]
        return next_date, next_avail[:3]

    return date_str, []


def _extract_with_gemini(
    message: str, draft: Dict[str, Any], business: Dict[str, Any]
) -> Dict[str, Any]:
    client = _get_gemini_client()
    now_local = _now_local(business)
    today_str = now_local.strftime("%Y-%m-%d")
    weekday_name = now_local.strftime("%A")

    fallback = {
        "intent": "book",
        "date": None,
        "time": None,
        "customer_name": None,
        "details": None,
        "skip_details": False,
    }
    if not client:
        return fallback

    prompt = (
        f"Today is {weekday_name}, {today_str} in timezone {business.get('timezone', 'Africa/Harare')}.\n"
        f"Business name: {business.get('business_name', 'Business')}.\n"
        f"Current booking draft: {json.dumps(draft)}\n"
        f"Customer message: {json.dumps(message)}\n\n"
        "Extract booking fields and intent. Return ONLY valid JSON with these keys:\n"
        "- intent: one of 'book', 'cancel', 'greeting_or_info'\n"
        "- date: 'YYYY-MM-DD' or null if not mentioned/clear\n"
        "- time: 24-hour 'HH:MM' or null if not mentioned/clear\n"
        "- customer_name: string or null if not mentioned\n"
        "- details: optional booking notes/service description string or null\n"
        "- skip_details: boolean (true if user says 'skip', 'none', 'no details', 'nothing')\n"
    )

    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw_text = (resp.text or "").strip()
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            return fallback
        parsed = json.loads(match.group(0))
        return {
            "intent": parsed.get("intent") or "book",
            "date": parsed.get("date"),
            "time": parsed.get("time"),
            "customer_name": parsed.get("customer_name"),
            "details": parsed.get("details"),
            "skip_details": bool(parsed.get("skip_details", False)),
        }
    except Exception as exc:
        print(f"[Gemini Parse Error]: {exc}")
        return fallback


def _empty_draft() -> Dict[str, Any]:
    return {
        "date": None,
        "time": None,
        "customer_name": None,
        "details": None,
        "details_asked": False,
    }


def handle_customer_message(text: str, sender_phone: str, business: Dict[str, Any]) -> str:
    biz_id = business["_id"]
    biz_name = business.get("business_name", "our business")
    session = get_session(biz_id, sender_phone)
    draft = dict(session["draft"]) if session and session.get("draft") else _empty_draft()

    extracted = _extract_with_gemini(text, draft, business)

    if extracted["intent"] == "cancel":
        clear_session(biz_id, sender_phone)
        return (
            f"To cancel an existing booking with *{biz_name}*, please share the booking date and time "
            "(or contact the business directly so they can free up your slot)."
        )

    # Merge newly extracted fields into draft
    if extracted["date"]:
        draft["date"] = extracted["date"]
        draft["time"] = None  # Reset time when a new date is chosen so availability is re-checked
    if extracted["time"]:
        draft["time"] = extracted["time"]
    if extracted["customer_name"]:
        draft["customer_name"] = extracted["customer_name"].strip()

    if draft["details_asked"] and draft["details"] is None:
        if extracted["skip_details"]:
            draft["details"] = ""
        elif extracted["details"]:
            draft["details"] = extracted["details"].strip()
        elif draft["date"] and draft["time"] and draft["customer_name"]:
            # Treat a short reply at the optional-details prompt as the details note itself
            cleaned_note = text.strip()
            if cleaned_note.lower() in {"skip", "none", "no", "nope", "nothing", "-"}:
                draft["details"] = ""
            else:
                draft["details"] = cleaned_note

    elif extracted["details"]:
        draft["details"] = extracted["details"].strip()

    # Validate date if provided
    if draft["date"]:
        is_open, reason = _is_date_open(business, draft["date"])
        if not is_open:
            alt_date, alt_slots = _find_alternative_slots(business, draft["date"], None)
            draft["date"] = None
            draft["time"] = None
            upsert_session(biz_id, sender_phone, draft)
            reason_msg = {
                "past_date": "That date has already passed.",
                "closed_date": "We're closed on that date.",
                "non_working_day": "We aren't open on that day of the week.",
            }.get(reason, "That date isn't available.")
            if alt_date and alt_slots:
                slots_str = ", ".join(alt_slots)
                return f"{reason_msg} Our next open day is *{alt_date}* (available times: {slots_str}). Which day and time would you like?"
            return f"{reason_msg} What open day and time would you like to book instead?"

    # Validate time & slot capacity if both date and time are present
    if draft["date"] and draft["time"]:
        valid_slots = _generate_time_slots(business)
        cap = int(business.get("slot_capacity", 1))
        booked = count_confirmed_bookings(biz_id, draft["date"], draft["time"])

        if draft["time"] not in valid_slots or booked >= cap:
            alt_date, alt_slots = _find_alternative_slots(business, draft["date"], draft["time"])
            chosen_time = draft["time"]
            draft["time"] = None
            if alt_date != draft["date"]:
                draft["date"] = None
            upsert_session(biz_id, sender_phone, draft)

            if alt_slots:
                slots_str = ", ".join(alt_slots)
                if alt_date == draft.get("date") or (alt_date and chosen_time not in valid_slots):
                    return (
                        f"*{chosen_time}* isn't available on that day. "
                        f"On *{alt_date}*, we have *{slots_str}* open—which works for you?"
                    )
                return (
                    f"*{chosen_time}* is fully booked on that day. "
                    f"Would *{slots_str}* on *{alt_date}* work instead?"
                )
            return f"*{chosen_time}* isn't available right now. Could you try another day or time?"

    # Ask for missing required fields one step at a time
    if not draft["date"] or not draft["time"]:
        upsert_session(biz_id, sender_phone, draft)
        if not draft["date"] and not draft["time"]:
            return (
                f"Welcome to *{biz_name}*! What *day/date* and *time* would you like to book? "
                f"(Hours: {business.get('open_time', '08:00')} – {business.get('close_time', '17:00')})"
            )
        if not draft["date"]:
            return f"Got it, *{draft['time']}*. Which *date or day* would you like to book for?"
        return f"Got it, *{draft['date']}*. What *time* would you prefer?"

    if not draft["customer_name"]:
        upsert_session(biz_id, sender_phone, draft)
        return (
            f"*{draft['date']}* at *{draft['time']}* is available! "
            "What *name* should I put the booking under?"
        )

    if draft["details"] is None and not draft["details_asked"]:
        draft["details_asked"] = True
        upsert_session(biz_id, sender_phone, draft)
        return (
            f"Thanks, *{draft['customer_name']}*. Any *booking details or notes* you'd like to include? "
            "(Reply *skip* if none.)"
        )

    # All required info collected -> atomic booking creation
    created = create_booking_if_available(
        business=business,
        date_str=draft["date"],
        time_str=draft["time"],
        customer_name=draft["customer_name"],
        customer_phone=sender_phone,
        details=draft["details"] or None,
    )

    if not created:
        # Race condition: someone took the last spot just now
        alt_date, alt_slots = _find_alternative_slots(business, draft["date"], draft["time"])
        draft["time"] = None
        upsert_session(biz_id, sender_phone, draft)
        slots_str = ", ".join(alt_slots) if alt_slots else "another time"
        return (
            f"Sorry, that spot was just taken! Available options on *{alt_date}*: *{slots_str}*. "
            "Which time would you like?"
        )

    clear_session(biz_id, sender_phone)
    details_line = f"\n• Details: {created['details']}" if created.get("details") else "\n• Details: None"
    return (
        f"✅ *Booking Confirmed — {biz_name}*\n"
        f"• Date: {created['date']}\n"
        f"• Time: {created['time']}\n"
        f"• Name: {created['customer_name']}"
        f"{details_line}"
    )