"""Browser-based scraping for Marriott availability."""

import asyncio
import os
import logging

log = logging.getLogger(__name__)

IS_CI = os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("CI") == "true"


def build_hotel_url(property_code: str) -> str:
    """Hotel overview page — used to warm up the session."""
    return f"https://www.marriott.com/hotels/travel/{property_code.lower()}"


def build_rate_url(property_code: str, checkin: str, checkout: str) -> str:
    return (
        f"https://www.marriott.com/reservation/rateListMenu.mi"
        f"?propertyCode={property_code}"
        f"&checkInDate={checkin}&checkOutDate={checkout}"
        f"&numberOfRooms=1&numberOfGuests=1"
    )


def build_booking_url(property_code: str, checkin: str, checkout: str) -> str:
    return (
        f"https://www.marriott.com/reservation/rateListMenu.mi"
        f"?propertyCode={property_code}"
        f"&checkInDate={checkin}&checkOutDate={checkout}"
    )


async def scrape_with_nodriver(property_code: str, rate_url: str) -> dict:
    """
    Scrape using undetected Chrome via nodriver.
    Strategy: visit hotel overview page first to clear Akamai challenge,
    then navigate to the rate/availability page.
    """
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
        # Step 1: Visit hotel overview page to establish session and clear Akamai
        hotel_url = build_hotel_url(property_code)
        log.info(f"Warming up session: {hotel_url}")
        tab = await browser.get(hotel_url)
        await tab.sleep(8)

        warmup_html = await tab.get_content()
        warmup_size = len(warmup_html)
        log.info(f"Warmup page: {warmup_size} bytes")

        # If still on Akamai challenge, wait longer
        if warmup_size < 5000 or "akamai" in warmup_html.lower():
            log.info("Akamai challenge detected, waiting for it to clear...")
            await tab.sleep(12)
            warmup_html = await tab.get_content()
            warmup_size = len(warmup_html)
            log.info(f"After wait: {warmup_size} bytes")

        # Step 2: Navigate to rate/availability page
        log.info(f"Loading rates page: {rate_url}")
        tab = await browser.get(rate_url)
        await tab.sleep(10)

        rate_html = await tab.get_content()
        rate_size = len(rate_html)
        log.info(f"Rates page: {rate_size} bytes")

        # If small, might be challenge — wait more
        if rate_size < 5000:
            log.info("Rate page small, waiting...")
            await tab.sleep(10)
            rate_html = await tab.get_content()
            rate_size = len(rate_html)
            log.info(f"After wait: {rate_size} bytes")

        return {
            "calendar_html": warmup_html,
            "rate_html": rate_html,
        }

    finally:
        try:
            browser.stop()
        except Exception:
            pass


def scrape_with_curl(property_code: str, rate_url: str) -> dict | None:
    """Fast scrape attempt with curl_cffi. Returns None if blocked."""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None

    log.info("Trying curl_cffi (fast path)...")
    session = cffi_requests.Session(impersonate="chrome131")

    try:
        # Warm up with hotel overview page
        hotel_url = build_hotel_url(property_code)
        session.get(hotel_url, timeout=15)

        rate_resp = session.get(rate_url, timeout=15)
        log.info(f"curl rates: HTTP {rate_resp.status_code}, {len(rate_resp.text)} bytes")

        if len(rate_resp.text) < 5000:
            log.info("curl_cffi got challenge page, falling back")
            return None

        return {"calendar_html": "", "rate_html": rate_resp.text}

    except Exception as e:
        log.info(f"curl_cffi failed: {e}")
        return None


def scrape(property_code: str, checkin_str: str, checkout_str: str) -> dict:
    """
    Scrape Marriott for a property. Tries curl first, falls back to nodriver.
    Returns dict with calendar_html, rate_html.
    """
    rate_url = build_rate_url(property_code, checkin_str, checkout_str)

    result = scrape_with_curl(property_code, rate_url)
    if result:
        result["mode"] = "curl_cffi"
        return result

    result = asyncio.run(scrape_with_nodriver(property_code, rate_url))
    result["mode"] = "nodriver"
    return result
