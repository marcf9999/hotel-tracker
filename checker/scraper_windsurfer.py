"""Scraper for Windsurfer CRS booking system (used by Glidden House, etc.)."""

import asyncio
import os
import logging
import re

log = logging.getLogger(__name__)

IS_CI = os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("CI") == "true"


def build_windsurfer_url(booking_url: str, checkin: str, checkout: str) -> str:
    """Build a Windsurfer search URL with dates. Dates in MM/DD/YYYY format."""
    base = booking_url.split("?")[0]
    prop_match = re.search(r'propertyID=(\d+)', booking_url)
    prop_id = prop_match.group(1) if prop_match else ""
    return f"{base}?propertyID={prop_id}&checkin={checkin}&checkout={checkout}"


async def scrape_windsurfer_nodriver(url: str) -> dict:
    """Scrape Windsurfer booking page using nodriver."""
    import nodriver as uc

    chrome_path = os.getenv("CHROME_PATH")
    browser_args = ["--window-size=1920,1080"]
    if IS_CI:
        browser_args.extend(["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
    else:
        browser_args.append("--window-position=-2000,-2000")

    browser = await uc.start(
        headless=IS_CI,
        browser_executable_path=chrome_path,
        browser_args=browser_args,
        sandbox=not IS_CI,
    )

    try:
        log.info(f"Loading Windsurfer page: {url}")
        tab = await browser.get(url)
        # Wait for dynamic content to load
        await tab.sleep(8)

        html = await tab.get_content()
        log.info(f"Windsurfer page: {len(html)} bytes")

        return {"html": html, "mode": "nodriver"}
    finally:
        try:
            browser.stop()
        except Exception:
            pass


def scrape_windsurfer_curl(url: str) -> dict | None:
    """Try fast scrape with curl_cffi."""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None

    log.info("Trying curl_cffi for Windsurfer...")
    session = cffi_requests.Session(impersonate="chrome131")

    try:
        resp = session.get(url, timeout=15)
        log.info(f"curl Windsurfer: HTTP {resp.status_code}, {len(resp.text)} bytes")

        # Windsurfer loads rates via JS, so small pages are incomplete
        if len(resp.text) < 5000:
            return None

        return {"html": resp.text, "mode": "curl_cffi"}
    except Exception as e:
        log.info(f"curl_cffi failed: {e}")
        return None


def analyze_windsurfer(html: str, checkin_str: str) -> dict:
    """
    Analyze Windsurfer booking page HTML for availability.

    Available signals: room names, prices, "Book" buttons
    Unavailable signals: "no availability", lead time exceeded, empty room list
    """
    content_lower = html.lower()

    if len(html) < 3000:
        return {
            "available": False,
            "details": "Page too small — may be blocked or failed to load.",
            "conclusive": False,
            "blocked": True,
            "nights": [],
        }

    # Check for lead time / date restriction
    lead_time_exceeded = any(phrase in content_lower for phrase in [
        "no availability", "no rooms available",
        "please select a valid", "date is not available",
        "exceeds the maximum", "not available for the selected",
    ])

    # Check for room availability - Windsurfer shows room cards with prices
    has_rooms = any(phrase in content_lower for phrase in [
        "book now", "per night", "select room", "room rate",
        "add to cart", "reserve", "rate details",
    ])

    # Try to extract prices
    prices = re.findall(r'\$\s*([\d,]+(?:\.\d{2})?)', html)
    # Filter out unrealistic prices (too small or too large)
    real_prices = []
    for p in prices:
        try:
            val = float(p.replace(",", ""))
            if 30 <= val <= 5000:  # reasonable hotel price range
                real_prices.append(val)
        except ValueError:
            pass

    # Look for room type names
    room_types = re.findall(
        r'(?:room-name|roomName|room-title)["\s>]+([^<]{3,50})', html, re.IGNORECASE
    )

    # Build night availability
    nights = [{
        "night_date": checkin_str,
        "is_available": has_rooms and not lead_time_exceeded,
        "price_cents": int(min(real_prices) * 100) if real_prices else None,
        "currency": "USD",
    }]

    log.info(f"Windsurfer: has_rooms={has_rooms}, lead_time={lead_time_exceeded}, "
             f"prices={real_prices[:5]}, room_types={room_types[:3]}")

    if has_rooms and not lead_time_exceeded:
        price_info = f" from ${min(real_prices):.0f}/night" if real_prices else ""
        return {
            "available": True,
            "details": f"Rooms available for {checkin_str}{price_info}",
            "conclusive": True,
            "blocked": False,
            "nights": nights,
        }
    elif lead_time_exceeded:
        return {
            "available": False,
            "details": f"Date {checkin_str} not yet available — may exceed booking window.",
            "conclusive": True,
            "blocked": False,
            "nights": nights,
        }
    else:
        # Page loaded but no clear signals either way
        # Check if we got actual page content (not a redirect or error)
        has_windsurfer = "windsurfer" in content_lower or "wsVars" in html.lower()
        if has_windsurfer:
            return {
                "available": False,
                "details": f"No rooms shown for {checkin_str} — likely not available yet.",
                "conclusive": True,
                "blocked": False,
                "nights": nights,
            }
        return {
            "available": False,
            "details": "Inconclusive — page may not have loaded properly.",
            "conclusive": False,
            "blocked": False,
            "nights": nights,
        }


def scrape_and_analyze(hotel: dict) -> dict:
    """Full scrape + analysis for a Windsurfer hotel."""
    ci = hotel["checkin_date"]
    co = hotel["checkout_date"]

    # Format dates MM/DD/YYYY
    ci_parts = ci.split("-")
    co_parts = co.split("-")
    ci_str = f"{ci_parts[1]}/{ci_parts[2]}/{ci_parts[0]}"
    co_str = f"{co_parts[1]}/{co_parts[2]}/{co_parts[0]}"

    url = build_windsurfer_url(hotel["booking_url"], ci_str, co_str)

    # Try curl first, fall back to nodriver
    result = scrape_windsurfer_curl(url)
    if not result:
        result = asyncio.run(scrape_windsurfer_nodriver(url))

    analysis = analyze_windsurfer(result["html"], ci)

    return {
        "status": "available" if analysis["available"] else
                  "blocked" if analysis.get("blocked") else "not_available",
        "details": analysis["details"],
        "blocked": analysis.get("blocked", False),
        "nights": analysis.get("nights", []),
        "calendar_bytes": len(result["html"]),
        "rates_bytes": 0,
        "mode": result["mode"],
    }
