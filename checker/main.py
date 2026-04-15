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

    if source == "airbnb":
        from .scraper_airbnb import scrape_and_analyze as scrape_airbnb
        return scrape_airbnb(hotel)

    # Marriott: scrape directly, fall back to Google Hotels if blocked
    return check_marriott_hotel(hotel)


def check_marriott_via_google(hotel: dict) -> dict | None:
    """Try Google Hotels first — avoids Marriott bot detection."""
    from .scraper_google import check_google_hotels

    checkin = date.fromisoformat(hotel["checkin_date"])
    checkout = date.fromisoformat(hotel["checkout_date"])

    log.info(f"Trying Google Hotels for {hotel['hotel_name']}...")
    result = check_google_hotels(hotel["hotel_name"], checkin, checkout)
    return result


def check_marriott_hotel(hotel: dict) -> dict:
    """Check a Marriott hotel directly, fall back to Google Hotels if blocked."""
    from .scraper import scrape
    from .analyzer import analyze_rates

    code = hotel["property_code"]
    ci = hotel["checkin_date"]
    co = hotel["checkout_date"]

    ci_parts = ci.split("-")
    co_parts = co.split("-")
    ci_str = f"{ci_parts[1]}/{ci_parts[2]}/{ci_parts[0]}"
    co_str = f"{co_parts[1]}/{co_parts[2]}/{co_parts[0]}"

    log.info(f"Marriott check: {hotel['hotel_name']} ({code})")

    try:
        html = scrape(code, ci_str, co_str)
    except Exception as e:
        log.error(f"Scrape failed for {code}: {e}")
        return _try_google_fallback(hotel, f"Scrape error: {e}")

    rate_result = analyze_rates(html["rate_html"])
    cal_bytes = len(html.get("calendar_html") or "")
    rate_bytes = len(html["rate_html"])

    if rate_result["conclusive"] and rate_result["available"]:
        return {
            "status": "available",
            "details": rate_result["details"],
            "blocked": False,
            "nights": [],
            "calendar_bytes": cal_bytes,
            "rates_bytes": rate_bytes,
            "mode": html["mode"],
        }

    if rate_result["conclusive"] and not rate_result["available"]:
        return {
            "status": "not_available",
            "details": rate_result["details"],
            "blocked": False,
            "nights": [],
            "calendar_bytes": cal_bytes,
            "rates_bytes": rate_bytes,
            "mode": html["mode"],
        }

    # Blocked or inconclusive — try Google Hotels as fallback
    rate_blocked = rate_result.get("blocked", False)
    if rate_blocked:
        log.info("Marriott blocked, trying Google Hotels fallback...")
        fallback = _try_google_fallback(hotel, rate_result["details"])
        if fallback:
            return fallback

    return {
        "status": "blocked" if rate_blocked else "error",
        "details": rate_result["details"],
        "blocked": rate_blocked,
        "nights": [],
        "calendar_bytes": cal_bytes,
        "rates_bytes": rate_bytes,
        "mode": html["mode"],
    }


def _try_google_fallback(hotel: dict, original_details: str) -> dict:
    """Try Google Hotels as a fallback when direct Marriott scraping fails."""
    try:
        google_result = check_marriott_via_google(hotel)
        if google_result:
            google_result["details"] = google_result["details"] + " (Google Hotels fallback)"
            return google_result
    except Exception as e:
        log.error(f"Google Hotels fallback failed: {e}")

    return {
        "status": "blocked",
        "details": original_details,
        "blocked": True,
        "nights": [],
        "calendar_bytes": 0,
        "rates_bytes": 0,
        "mode": "error",
    }


def main():
    from . import db
    from .notifier import send_summary_email

    log.info("=" * 60)
    log.info("Hotel Availability Checker — Starting run")

    hotels = db.get_active_hotels()
    log.info(f"Found {len(hotels)} active hotel(s) to check")

    all_results = []

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

        log.info(f"{result['status'].upper()}: {hotel['hotel_name']} — {result['details']}")

        all_results.append({
            "hotel": hotel,
            "status": result["status"],
            "details": result["details"],
        })

    # Send one consolidated summary email
    if all_results:
        send_summary_email(all_results)

    log.info("Run complete")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
