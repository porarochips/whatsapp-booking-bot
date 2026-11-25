import time
from datetime import datetime
from typing import Any, Dict, Set, Tuple
import pytz
from database import get_bookings_for_date, get_db
from delivery import deliver_daily_report
from pdf_reporter import generate_daily_bookings_pdf

_sent_today_tracker: Set[Tuple[str, str]] = set()


def run_report_for_business(business: Dict[str, Any], date_str: str) -> None:
    bookings = get_bookings_for_date(business["_id"], date_str)
    pdf_path = generate_daily_bookings_pdf(business, date_str, bookings)
    deliver_daily_report(business, date_str, len(bookings), pdf_path)


def check_and_run_scheduled_reports() -> None:
    db = get_db()
    businesses = list(db.businesses.find({"active": True}))

    for biz in businesses:
        tz_name = biz.get("timezone", "Africa/Harare")
        now_local = datetime.now(pytz.timezone(tz_name))
        date_str = now_local.strftime("%Y-%m-%d")
        hhmm_now = now_local.strftime("%H:%M")
        target_hhmm = biz.get("report_time", "06:30")

        key = (str(biz["_id"]), date_str)
        if hhmm_now == target_hhmm and key not in _sent_today_tracker:
            run_report_for_business(biz, date_str)
            _sent_today_tracker.add(key)


def start_scheduler_loop(poll_seconds: int = 30) -> None:
    while True:
        try:
            check_and_run_scheduled_reports()
        except Exception as exc:
            print(f"[Scheduler Error]: {exc}")
        time.sleep(poll_seconds)


if __name__ == "__main__":
    start_scheduler_loop()