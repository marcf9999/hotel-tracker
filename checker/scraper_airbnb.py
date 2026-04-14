"""Scraper for Airbnb listings via the public calendar API."""

import json
import logging
import re
from datetime import date, timedelta

log = logging.getLogger(__name__)

# Public API key embedded in Airbnb's frontend JS
AIRBNB_API_KEY = "d306zoyjsyarp7ifhu67rjxn52tv0t20"

# Persisted query hash for PdpAvailabilityCalendar operation
CALENDAR_QUERY_HASH = "8f08e03c7bd16fcad3c92a3592c19a8b559a0d0e065e7f2571b69df2e7da3b77"


def extract_listing_id(url: str) -> str:
    """Extract listing ID from an Airbnb URL like /rooms/607165805451024818."""
    match = re.search(r'/rooms/(\d+)', url)
    if match:
        return match.group(1)
    raise ValueError(f"Cannot extract listing ID from: {url}")


def fetch_calendar(listing_id: str, checkin: date, checkout: date) -> tuple[dict | None, int]:
    """Fetch availability calendar from Airbnb API. Returns (data, raw_bytes)."""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        log.error("curl_cffi not available")
        return None, 0

    # Calculate how many months to fetch
    month_span = (checkout.year - checkin.year) * 12 + (checkout.month - checkin.month) + 1

    variables = json.dumps({
        "request": {
            "count": month_span,
            "listingId": listing_id,
            "month": checkin.month,
            "year": checkin.year,
        }
    })

    extensions = json.dumps({
        "persistedQuery": {
            "version": 1,
            "sha256Hash": CALENDAR_QUERY_HASH,
        }
    })

    url = "https://www.airbnb.com/api/v3/PdpAvailabilityCalendar"
    params = {
        "operationName": "PdpAvailabilityCalendar",
        "locale": "en",
        "currency": "USD",
        "variables": variables,
        "extensions": extensions,
    }

    headers = {
        "X-Airbnb-Api-Key": AIRBNB_API_KEY,
        "Content-Type": "application/json",
    }

    session = cffi_requests.Session(impersonate="chrome131")

    try:
        resp = session.get(url, params=params, headers=headers, timeout=15)
        raw_bytes = len(resp.text)
        log.info(f"Airbnb calendar API: HTTP {resp.status_code}, {raw_bytes} bytes")

        if resp.status_code != 200:
            log.error(f"Airbnb API error: HTTP {resp.status_code}")
            return None, raw_bytes

        data = resp.json()
        return data, raw_bytes
    except Exception as e:
        log.error(f"Airbnb calendar fetch failed: {e}")
        return None, 0


def analyze_calendar(data: dict, checkin: date, checkout: date) -> dict:
    """Parse Airbnb calendar API response into nights list."""
    # Build set of target night dates (checkin to checkout-1)
    num_nights = (checkout - checkin).days
    target_dates = set()
    for i in range(num_nights):
        target_dates.add((checkin + timedelta(days=i)).isoformat())

    nights = []
    found_dates = set()

    # Navigate the response structure
    try:
        calendar_months = (
            data.get("data", {})
            .get("merlin", {})
            .get("pdpAvailabilityCalendar", {})
            .get("calendarMonths", [])
        )
    except (AttributeError, TypeError):
        calendar_months = []

    for month in calendar_months:
        for day in month.get("days", []):
            cal_date = day.get("calendarDate")
            if cal_date not in target_dates:
                continue

            found_dates.add(cal_date)
            is_available = day.get("available", False)

            price_cents = None
            price_obj = day.get("price", {})
            if price_obj:
                # Try to get the total price amount
                amount = price_obj.get("amount")
                if amount is not None:
                    price_cents = int(float(amount) * 100)
                elif price_obj.get("priceFormatted"):
                    # Parse from formatted string like "$149"
                    price_match = re.search(r'[\$€£]([\d,]+)', price_obj["priceFormatted"])
                    if price_match:
                        price_cents = int(float(price_match.group(1).replace(",", "")) * 100)

            nights.append({
                "night_date": cal_date,
                "is_available": is_available,
                "price_cents": price_cents,
                "currency": "USD",
            })

    # Any target dates not found in response — mark unavailable
    for d in sorted(target_dates - found_dates):
        nights.append({
            "night_date": d,
            "is_available": False,
            "price_cents": None,
            "currency": "USD",
        })

    # Sort by date
    nights.sort(key=lambda n: n["night_date"])

    avail_count = sum(1 for n in nights if n["is_available"])
    total = len(nights)
    any_available = avail_count > 0

    log.info(f"Airbnb calendar: {avail_count}/{total} nights available")

    if any_available:
        priced = [n for n in nights if n["price_cents"]]
        price_info = f" from ${min(n['price_cents'] for n in priced)/100:.0f}/night" if priced else ""
        details = f"{avail_count}/{total} nights available{price_info}"
    elif not calendar_months:
        details = "No calendar data returned — API may have changed."
    else:
        details = f"All {total} nights unavailable for {checkin} to {checkout}"

    return {
        "available": any_available,
        "details": details,
        "nights": nights,
        "has_data": len(calendar_months) > 0,
    }


def scrape_and_analyze(hotel: dict) -> dict:
    """Full scrape + analysis for an Airbnb listing. Entry point called by main.py."""
    listing_id = extract_listing_id(hotel["booking_url"])
    checkin = date.fromisoformat(hotel["checkin_date"])
    checkout = date.fromisoformat(hotel["checkout_date"])

    log.info(f"Airbnb check: listing {listing_id} for {checkin} to {checkout}")

    data, raw_bytes = fetch_calendar(listing_id, checkin, checkout)

    if data is None:
        return {
            "status": "error",
            "details": "Failed to fetch Airbnb calendar API",
            "blocked": False,
            "nights": [],
            "calendar_bytes": raw_bytes,
            "rates_bytes": 0,
            "mode": "curl_cffi",
        }

    analysis = analyze_calendar(data, checkin, checkout)

    if analysis["available"]:
        status = "available"
    elif analysis["has_data"]:
        status = "not_available"
    else:
        status = "error"

    return {
        "status": status,
        "details": analysis["details"],
        "blocked": False,
        "nights": analysis["nights"],
        "calendar_bytes": raw_bytes,
        "rates_bytes": 0,
        "mode": "curl_cffi",
    }
