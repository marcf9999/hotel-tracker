"""Browser-based scraping for Marriott availability."""

import asyncio
import os
import logging

log = logging.getLogger(__name__)

IS_CI = os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("CI") == "true"


def build_calendar_url(property_code: str) -> str:
    return (
        f"https://www.marriott.com/search/availabilityCalendar.mi"
        f"?isRateCalendar=true&propertyCode={property_code}"
        f"&isSearch=true&currency=&showFullPrice=false&costTab=total&isAdultsOnly=false"
    )


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


async def scrape_with_nodriver(calendar_url: str, rate_url: str) -> dict:
    """Scrape using undetected Chrome via nodriver."""
    import nodriver as uc

    chrome_path = os.getenv("CHROME_PATH")
    browser_args = ["--window-size=1920,1080"]
    if IS_CI:
        browser_args.append("--no-sandbox")
    else:
        browser_args.append("--window-position=-2000,-2000")

    browser = await uc.start(
        headless=False,
        browser_executable_path=chrome_path,
        browser_args=browser_args,
        sandbox=not IS_CI,
    )

    try:
        # Calendar page
        log.info("Loading calendar page...")
        tab = await browser.get(calendar_url)
        await tab.sleep(10)

        cal_html = await tab.get_content()
        if "akamai" in cal_html.lower() or len(cal_html) < 3000:
            log.info("Waiting for Akamai challenge...")
            await tab.sleep(10)
            cal_html = await tab.get_content()

        log.info(f"Calendar: {len(cal_html)} bytes")

        # Rate page
        log.info("Loading rate page...")
        tab = await browser.get(rate_url)
        await tab.sleep(10)
        rate_html = await tab.get_content()
        log.info(f"Rates: {len(rate_html)} bytes")

        return {"calendar_html": cal_html, "rate_html": rate_html}

    finally:
        try:
            browser.stop()
        except Exception:
            pass


def scrape_with_curl(calendar_url: str, rate_url: str) -> dict | None:
    """Fast scrape attempt with curl_cffi. Returns None if blocked."""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None

    log.info("Trying curl_cffi (fast path)...")
    session = cffi_requests.Session(impersonate="chrome131")

    try:
        session.get("https://www.marriott.com", timeout=15)

        cal_resp = session.get(calendar_url, timeout=15)
        log.info(f"curl calendar: HTTP {cal_resp.status_code}, {len(cal_resp.text)} bytes")

        rate_resp = session.get(rate_url, timeout=15)
        log.info(f"curl rates: HTTP {rate_resp.status_code}, {len(rate_resp.text)} bytes")

        # If both are small, it's an Akamai challenge — inconclusive
        if len(cal_resp.text) < 3000 and len(rate_resp.text) < 3000:
            log.info("curl_cffi got challenge pages, falling back")
            return None

        return {"calendar_html": cal_resp.text, "rate_html": rate_resp.text}

    except Exception as e:
        log.info(f"curl_cffi failed: {e}")
        return None


def scrape(property_code: str, checkin_str: str, checkout_str: str) -> dict:
    """
    Scrape Marriott for a property. Tries curl first, falls back to nodriver.
    Returns dict with calendar_html, rate_html.
    """
    cal_url = build_calendar_url(property_code)
    rate_url = build_rate_url(property_code, checkin_str, checkout_str)

    result = scrape_with_curl(cal_url, rate_url)
    if result:
        result["mode"] = "curl_cffi"
        return result

    result = asyncio.run(scrape_with_nodriver(cal_url, rate_url))
    result["mode"] = "nodriver"
    return result
