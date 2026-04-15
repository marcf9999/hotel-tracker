"""Scraper for Airbnb listings via listing page HTML parsing."""

import json
import logging
import re
from datetime import date, timedelta

log = logging.getLogger(__name__)


def extract_listing_id(url: str) -> str:
    """Extract listing ID from an Airbnb URL like /rooms/607165805451024818."""
    match = re.search(r'/rooms/(\d+)', url)
    if match:
        return match.group(1)
    raise ValueError(f"Cannot extract listing ID from: {url}")


def fetch_listing_page(listing_id: str, checkin: date, checkout: date) -> tuple[str, int]:
    """Fetch the Airbnb listing page with dates. Returns (html, byte_count)."""
    from curl_cffi import requests as cffi_requests

    url = (
        f"https://www.airbnb.com/rooms/{listing_id}"
        f"?check_in={checkin.isoformat()}&check_out={checkout.isoformat()}&adults=1"
    )

    session = cffi_requests.Session(impersonate="chrome131")

    try:
        resp = session.get(url, timeout=20)
        raw_bytes = len(resp.text)
        log.info(f"Airbnb listing page: HTTP {resp.status_code}, {raw_bytes} bytes")

        if resp.status_code != 200:
            log.error(f"Airbnb page error: HTTP {resp.status_code}")
            return "", raw_bytes

        return resp.text, raw_bytes
    except Exception as e:
        log.error(f"Airbnb page fetch failed: {e}")
        return "", 0


def analyze_listing_page(html: str, checkin: date, checkout: date) -> dict:
    """
    Analyze Airbnb listing page HTML for availability signals.

    Key signals in the SSR data:
    - structuredDisplayPrice not null → available with pricing
    - localizedUnavailabilityMessage not null → not available
    - integratedPill with cancellation policy → available
    - selectedDatesLink with date title → dates recognized
    """
    if len(html) < 5000:
        return {
            "available": False,
            "details": "Page too small — may be blocked or failed to load.",
            "nights": [],
            "has_data": False,
        }

    num_nights = (checkout - checkin).days

    # Check for unavailability message
    unavail_match = re.search(
        r'"localizedUnavailabilityMessage"\s*:\s*"([^"]+)"', html
    )
    if unavail_match:
        msg = unavail_match.group(1)
        log.info(f"Airbnb: unavailable — {msg}")
        nights = []
        for i in range(num_nights):
            d = (checkin + timedelta(days=i)).isoformat()
            nights.append({
                "night_date": d,
                "is_available": False,
                "price_cents": None,
                "currency": "USD",
            })
        return {
            "available": False,
            "details": f"Not available: {msg}",
            "nights": nights,
            "has_data": True,
        }

    # Check for pricing data (strongest availability signal)
    has_price = False
    price_cents = None

    # Look for structured price
    price_match = re.search(
        r'"structuredDisplayPrice"\s*:\s*\{[^}]*"primaryLine"[^}]*"price"\s*:\s*"([^"]+)"',
        html,
    )
    if price_match:
        has_price = True
        raw_price = price_match.group(1)
        cents = _parse_price(raw_price)
        if cents:
            price_cents = cents

    # Look for any price display
    if not has_price:
        price_display = re.search(r'"priceString"\s*:\s*"\$(\d[\d,]*)"', html)
        if price_display:
            has_price = True
            price_cents = int(float(price_display.group(1).replace(",", "")) * 100)

    # Check for book button (reliable availability signal)
    has_book_button = bool(re.search(
        r'"bookItButtonByPlacement"\s*:\s*\{', html
    ))

    # Check for dates being recognized
    dates_recognized = bool(re.search(
        r'"selectedDatesLink":\s*\{[^}]*"title"\s*:\s*"[^"]*\w+ \d+',
        html,
    ))

    # Check for canInstantBook
    can_book = bool(re.search(r'"canInstantBook"\s*:\s*true', html))

    log.info(f"Airbnb signals: price={has_price}, book_button={has_book_button}, "
             f"dates_recognized={dates_recognized}, can_book={can_book}")

    # Only report available when we have strong evidence: actual pricing or book button
    nights = []
    is_available = has_price or has_book_button or can_book
    for i in range(num_nights):
        d = (checkin + timedelta(days=i)).isoformat()
        nights.append({
            "night_date": d,
            "is_available": is_available,
            "price_cents": price_cents,
            "currency": "USD",
        })

    if is_available:
        price_info = f" — ${price_cents / 100:.0f}/night" if price_cents else ""
        details = f"Available for {checkin} to {checkout}{price_info}"
    elif dates_recognized:
        # Dates recognized but no clear availability signals
        details = f"Dates recognized but availability unclear for {checkin} to {checkout}"
    else:
        details = f"Could not determine availability for {checkin} to {checkout}"

    return {
        "available": is_available,
        "details": details,
        "nights": nights,
        "has_data": dates_recognized or has_price or has_cancellation,
    }


def _parse_price(text: str) -> int | None:
    """Parse a price string like '$149' or '€120' into cents."""
    match = re.search(r'[\$€£]([\d,]+(?:\.\d{2})?)', text)
    if match:
        return int(float(match.group(1).replace(",", "")) * 100)
    return None


def scrape_and_analyze(hotel: dict) -> dict:
    """Full scrape + analysis for an Airbnb listing. Entry point called by main.py."""
    listing_id = extract_listing_id(hotel["booking_url"])
    checkin = date.fromisoformat(hotel["checkin_date"])
    checkout = date.fromisoformat(hotel["checkout_date"])

    log.info(f"Airbnb check: listing {listing_id} for {checkin} to {checkout}")

    html, raw_bytes = fetch_listing_page(listing_id, checkin, checkout)

    if not html:
        return {
            "status": "error",
            "details": "Failed to fetch Airbnb listing page",
            "blocked": False,
            "nights": [],
            "calendar_bytes": raw_bytes,
            "rates_bytes": 0,
            "mode": "curl_cffi",
        }

    analysis = analyze_listing_page(html, checkin, checkout)

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
