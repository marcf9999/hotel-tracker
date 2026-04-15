"""Check hotel availability via Google Hotels search — avoids hotel site bot detection."""

import logging
import re
from datetime import date, timedelta

log = logging.getLogger(__name__)


def check_google_hotels(hotel_name: str, checkin: date, checkout: date) -> dict | None:
    """
    Query Google Hotels for a hotel's availability and pricing.
    Returns a result dict or None if Google Hotels didn't have useful data.
    """
    from curl_cffi import requests as cffi_requests

    query = hotel_name.replace(" ", "+")
    url = (
        f"https://www.google.com/travel/search"
        f"?q={query}&dates={checkin.isoformat()},{checkout.isoformat()}&hl=en"
    )

    session = cffi_requests.Session(impersonate="chrome131")

    try:
        resp = session.get(url, timeout=20)
        html = resp.text
        raw_bytes = len(html)
        log.info(f"Google Hotels: HTTP {resp.status_code}, {raw_bytes} bytes")

        if resp.status_code != 200 or raw_bytes < 10000:
            log.error(f"Google Hotels failed: HTTP {resp.status_code}, {raw_bytes} bytes")
            return None

        return analyze_google_hotels(html, hotel_name, checkin, checkout, raw_bytes)

    except Exception as e:
        log.error(f"Google Hotels fetch failed: {e}")
        return None


def analyze_google_hotels(html: str, hotel_name: str, checkin: date,
                          checkout: date, raw_bytes: int) -> dict | None:
    """Parse Google Hotels search results for availability and pricing."""
    num_nights = (checkout - checkin).days

    # Check if Google recognizes this as a specific hotel (entity page)
    # Google shows "typically costs between $X-$Y per night" for the main hotel
    price_range = re.search(
        r'(?:typically costs between|usually costs between|costs between)\s*'
        r'\$(\d[\d,]*)\s*.\s*\$(\d[\d,]*)\s*per night',
        html, re.IGNORECASE,
    )

    # Look for a single nightly price near the hotel name
    # Google shows "$XXX/night" or "$XXX per night"
    single_price = re.search(
        r'\$(\d[\d,]*)\s*(?:<[^>]*>)*\s*/?\s*night',
        html,
    )

    # Check for "sold out" or "unavailable" signals
    is_sold_out = bool(re.search(
        r'(sold\s*out|no\s*availability|unavailable\s*for)',
        html, re.IGNORECASE,
    ))

    # Look for "Check availability" or "View prices" buttons (means data exists)
    has_data = bool(re.search(
        r'(check availability|view prices|view deal|visit site)',
        html, re.IGNORECASE,
    ))

    # Extract the best price
    price_cents = None
    if price_range:
        low = int(price_range.group(1).replace(",", ""))
        price_cents = low * 100
        log.info(f"Google Hotels: price range ${low}-${price_range.group(2)}/night")
    elif single_price:
        price_cents = int(single_price.group(1).replace(",", "")) * 100
        log.info(f"Google Hotels: price ${single_price.group(1)}/night")

    if is_sold_out:
        log.info("Google Hotels: sold out")
        nights = _build_nights(checkin, num_nights, False, None)
        return {
            "status": "not_available",
            "details": f"Sold out on Google Hotels for {checkin} to {checkout}",
            "blocked": False,
            "nights": nights,
            "calendar_bytes": raw_bytes,
            "rates_bytes": 0,
            "mode": "google_hotels",
        }

    if price_cents:
        nights = _build_nights(checkin, num_nights, True, price_cents)
        price_str = f"${price_cents // 100}/night"
        if price_range:
            price_str = f"${price_range.group(1)}-${price_range.group(2)}/night"
        return {
            "status": "available",
            "details": f"Available on Google Hotels — {price_str}",
            "blocked": False,
            "nights": nights,
            "calendar_bytes": raw_bytes,
            "rates_bytes": 0,
            "mode": "google_hotels",
        }

    if has_data and not is_sold_out:
        # Google has data but no clear price — likely available
        nights = _build_nights(checkin, num_nights, True, None)
        return {
            "status": "available",
            "details": f"Listed on Google Hotels for {checkin} to {checkout} (price not extracted)",
            "blocked": False,
            "nights": nights,
            "calendar_bytes": raw_bytes,
            "rates_bytes": 0,
            "mode": "google_hotels",
        }

    # No useful data from Google Hotels
    log.info("Google Hotels: no useful data found")
    return None


def _build_nights(checkin: date, num_nights: int, available: bool,
                  price_cents: int | None) -> list[dict]:
    """Build a list of night availability dicts."""
    nights = []
    for i in range(num_nights):
        d = (checkin + timedelta(days=i)).isoformat()
        nights.append({
            "night_date": d,
            "is_available": available,
            "price_cents": price_cents,
            "currency": "USD",
        })
    return nights
