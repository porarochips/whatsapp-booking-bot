import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional
import pytz
from database import (
    add_closed_date,
    cancel_booking_by_time_or_id,
    get_bookings_for_date,
    remove_closed_date,
    update_business_fields,
)


def _business_today_str(business: Dict[str, Any]) -> str:
    tz_name = business.get("timezone", "Africa/Harare")
    tz = pytz.timezone(tz_name)
    return datetime.now(tz).strftime("%Y-%m-%d")


def _parse_date_token(token: str, business: Dict[str, Any]) -> Optional[str]:
    cleaned = token.strip().lower()
    tz = pytz.timezone(business.get("timezone", "Africa/Harare"))
    now_local = datetime.now(tz)

    if cleaned == "today":
        return now_local.strftime("%Y-%m-%d")
    if cleaned == "tomorrow":
        return (now_local + timedelta(days=1)).strftime("%Y-%m-%d")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", token.strip()):
        try:
            datetime.strptime(token.strip(), "%Y-%m-%d")
            return token.strip()
        except ValueError:
            return None
    return None


def _normalize_time(t: str) -> Optional[str]:
    t = t.strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def handle_owner_command(
    text: str,
    business: Dict[str, Any],
    on_trigger_pdf: Optional[Callable[[Dict[str, Any], str], None]] = None,
) -> str:
    raw = text.strip()
    upper = raw.upper()
    biz_id = business["_id"]
    today_str = _business_today_str(business)

    if upper in ("HELP", "?"):
        return (
            f"🛠 *Owner Commands — {business.get('business_name', 'Business')}*\n"
            "• `STATUS` — View hours, capacity & today's bookings\n"
            "• `SET CAPACITY <number>` — e.g. `SET CAPACITY 3`\n"
            "• `SET HOURS HH:MM-HH:MM` — e.g. `SET HOURS 08:00-17:00`\n"
            "• `CLOSE <YYYY-MM-DD|TODAY|TOMORROW>` — Block a date\n"
            "• `OPEN <YYYY-MM-DD|TODAY|TOMORROW>` — Unblock a date\n"
            "• `CANCEL <HH:MM>` — Cancel today's booking at that time\n"
            "• `TODAY` or `PDF NOW` — Send today's PDF report now"
        )

    if upper in ("STATUS", "SETTINGS"):
        bookings = get_bookings_for_date(biz_id, today_str)
        return (
            f"📊 *{business.get('business_name', 'Business')} Status ({today_str})*\n"
            f"• Hours: {business.get('open_time')} – {business.get('close_time')}\n"
            f"• Slot duration: {business.get('slot_duration_mins', 60)} mins\n"
            f"• Capacity per slot: {business.get('slot_capacity', 1)}\n"
            f"• Confirmed bookings today: {len(bookings)}"
        )

    cap_match = re.fullmatch(r"SET\s+CAPACITY\s+(\d+)", upper)
    if cap_match:
        new_cap = int(cap_match.group(1))
        if new_cap < 1 or new_cap > 100:
            return "⚠️ Capacity must be between 1 and 100."
        update_business_fields(biz_id, {"slot_capacity": new_cap})
        return f"✅ Slot capacity updated to *{new_cap}* booking(s) per slot."

    hours_match = re.fullmatch(r"SET\s+HOURS\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", upper)
    if hours_match:
        open_t = _normalize_time(hours_match.group(1))
        close_t = _normalize_time(hours_match.group(2))
        if not open_t or not close_t or open_t >= close_t:
            return "⚠️ Invalid hours. Use 24-hour format like `SET HOURS 08:00-17:00`."
        update_business_fields(biz_id, {"open_time": open_t, "close_time": close_t})
        return f"✅ Working hours updated to *{open_t} – {close_t}*."

    close_match = re.fullmatch(r"CLOSE\s+(.+)", upper)
    if close_match:
        parsed_date = _parse_date_token(close_match.group(1), business)
        if not parsed_date:
            return "⚠️ Use `CLOSE YYYY-MM-DD`, `CLOSE TODAY`, or `CLOSE TOMORROW`."
        add_closed_date(biz_id, parsed_date)
        return f"🚫 *{parsed_date}* has been marked as closed for bookings."

    open_match = re.fullmatch(r"OPEN\s+(.+)", upper)
    if open_match:
        parsed_date = _parse_date_token(open_match.group(1), business)
        if not parsed_date:
            return "⚠️ Use `OPEN YYYY-MM-DD`, `OPEN TODAY`, or `OPEN TOMORROW`."
        remove_closed_date(biz_id, parsed_date)
        return f"✅ *{parsed_date}* is now open for bookings."

    cancel_match = re.fullmatch(r"CANCEL\s+(.+)", upper)
    if cancel_match:
        target = cancel_match.group(1).strip()
        norm_time = _normalize_time(target) or target
        cancelled = cancel_booking_by_time_or_id(biz_id, today_str, norm_time)
        if not cancelled:
            return f"⚠️ No confirmed booking found for `{target}` on {today_str}."
        return (
            f"🗑 Cancelled booking at *{cancelled['time']}* on {today_str} "
            f"({cancelled.get('customer_name', 'Customer')}). Slot is now open."
        )

    if upper in ("TODAY", "PDF NOW"):
        if on_trigger_pdf:
            on_trigger_pdf(business, today_str)
            return f"📄 Generating and sending today's ({today_str}) report now..."
        return "ℹ️ PDF sender is not wired yet (coming in Step 3)."

    return "❓ Unrecognized owner command. Send `HELP` to see available commands."