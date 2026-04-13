"""
Hotel Availability Checker — Main Entry Point
Reads hotels from Supabase, checks each one, writes results back.
"""

import logging
import sys
import os
from datetime import date, datetime

from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def check_hotel(hotel: dict) -> dict:
    """Check a single hotel and return the result."""
    source = hotel.get("source", "marriott")
    log.info(f"Checking {hotel['hotel_name']} ({hotel['property_code']}) "
             f"for {hotel['checkin_date']} to {hotel['checkout_date']} [source={source}]")

    if source == "windsurfer":
        from .scraper_windsurfer import scrape_and_analyze
        return scrape_and_analyze(hotel)

    return check_marriott_hotel(hotel)


def check_marriott_hotel(hotel: dict) -> dict:
    """Check a Marriott hotel."""
    from .scraper import scrape
    from .analyzer import analyze_calendar, analyze_rates

    code = hotel["property_code"]
    ci = hotel["checkin_date"]
    co = hotel["checkout_date"]

    ci_parts = ci.split("-")
    co_parts = co.split("-")
    ci_str = f"{ci_parts[1]}/{ci_parts[2]}/{ci_parts[0]}"
    co_str = f"{co_parts[1]}/{co_parts[2]}/{co_parts[0]}"

    checkin_date = date.fromisoformat(ci)
    checkout_date = date.fromisoformat(co)

    log.info(f"Marriott check: {hotel['hotel_name']} ({code})")

    try:
        html = scrape(code, ci_str, co_str)
    except Exception as e:
        log.error(f"Scrape failed for {code}: {e}")
        return {
            "status": "error",
            "details": f"Scrape error: {e}",
            "blocked": True,
            "nights": [],
            "calendar_bytes": 0,
            "rates_bytes": 0,
            "mode": "error",
        }

    cal_result = analyze_calendar(html["calendar_html"], checkin_date, checkout_date)
    rate_result = analyze_rates(html["rate_html"])

    nights = cal_result.get("nights", [])

    if cal_result["conclusive"] and cal_result["available"]:
        return {
            "status": "available",
            "details": cal_result["details"],
            "blocked": False,
            "nights": nights,
            "calendar_bytes": len(html["calendar_html"]),
            "rates_bytes": len(html["rate_html"]),
            "mode": html["mode"],
        }

    if rate_result["conclusive"] and rate_result["available"]:
        return {
            "status": "available",
            "details": rate_result["details"],
            "blocked": False,
            "nights": nights,
            "calendar_bytes": len(html["calendar_html"]),
            "rates_bytes": len(html["rate_html"]),
            "mode": html["mode"],
        }

    # Not available — determine if blocked
    cal_blocked = cal_result.get("blocked", False)
    rate_blocked = rate_result.get("blocked", False)
    both_blocked = cal_blocked and rate_blocked

    if both_blocked:
        status = "blocked"
        details = "Both pages blocked by bot detection."
    elif cal_result["conclusive"]:
        status = "not_available"
        details = cal_result["details"]
    elif rate_result["conclusive"]:
        status = "not_available"
        details = rate_result["details"]
    else:
        status = "blocked" if (cal_blocked or rate_blocked) else "error"
        details = cal_result["details"] + " | " + rate_result["details"]

    return {
        "status": status,
        "details": details,
        "blocked": both_blocked,
        "nights": nights,
        "calendar_bytes": len(html["calendar_html"]),
        "rates_bytes": len(html["rate_html"]),
        "mode": html["mode"],
    }


def main():
    from . import db
    from .notifier import send_availability_alert, send_blocked_alert

    log.info("=" * 60)
    log.info("Hotel Availability Checker — Starting run")

    hotels = db.get_active_hotels()
    log.info(f"Found {len(hotels)} active hotel(s) to check")

    for hotel in hotels:
        result = check_hotel(hotel)

        # Write check run to DB
        run_id = db.insert_check_run(
            hotel_id=hotel["id"],
            status=result["status"],
            details=result["details"],
            calendar_bytes=result["calendar_bytes"],
            rates_bytes=result["rates_bytes"],
            checker_mode=result["mode"],
        )

        # Write per-night availability
        night_rows = []
        for n in result["nights"]:
            night_rows.append({
                "check_run_id": run_id,
                "hotel_id": hotel["id"],
                "night_date": n["night_date"],
                "is_available": n["is_available"],
                "price_cents": n.get("price_cents"),
                "currency": n.get("currency", "USD"),
            })
        db.insert_night_availability(night_rows)

        # Notifications
        if result["status"] == "available":
            log.info(f"AVAILABLE: {hotel['hotel_name']} — {result['details']}")
            send_availability_alert(hotel, result["details"], result["nights"])
        elif result["status"] == "blocked":
            log.warning(f"BLOCKED: {hotel['hotel_name']} — {result['details']}")
            send_blocked_alert(hotel, result["details"])
        else:
            log.info(f"{result['status'].upper()}: {hotel['hotel_name']} — {result['details']}")

    log.info("Run complete")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
