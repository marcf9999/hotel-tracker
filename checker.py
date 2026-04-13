"""
Marriott Hotel Availability Checker
Checks if rooms are available at the Cleveland Marriott East (CLECE)
for May 12-16, 2027 and sends an email notification when they open up.

Designed to run in GitHub Actions or locally.
- Locally: uses nodriver (undetected Chrome) to bypass Akamai
- GitHub Actions: uses Playwright with stealth (set env GITHUB_ACTIONS=true)
"""

import asyncio
import json
import os
import sys
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

# Setup
SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

LOG_FILE = SCRIPT_DIR / "checker.log"
STATE_DIR = SCRIPT_DIR / "state"
STATE_DIR.mkdir(exist_ok=True)

AVAIL_STATE = STATE_DIR / "last_avail_notified.txt"
BLOCK_STATE = STATE_DIR / "last_block_notified.txt"
RUN_HISTORY = STATE_DIR / "run_history.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# Configuration
PROPERTY_CODE = "CLECE"
TARGET_CHECKIN = "05/12/2027"
TARGET_CHECKOUT = "05/16/2027"

BOOKING_LINK = (
    f"https://www.marriott.com/reservation/rateListMenu.mi"
    f"?propertyCode={PROPERTY_CODE}"
    f"&checkInDate={TARGET_CHECKIN}&checkOutDate={TARGET_CHECKOUT}"
)

CALENDAR_URL = (
    f"https://www.marriott.com/search/availabilityCalendar.mi"
    f"?isRateCalendar=true&propertyCode={PROPERTY_CODE}"
    f"&isSearch=true&currency=&showFullPrice=false&costTab=total&isAdultsOnly=false"
)

RATE_URL = (
    f"https://www.marriott.com/reservation/rateListMenu.mi"
    f"?propertyCode={PROPERTY_CODE}"
    f"&checkInDate={TARGET_CHECKIN}&checkOutDate={TARGET_CHECKOUT}"
    f"&numberOfRooms=1&numberOfGuests=1"
)

IS_CI = os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("CI") == "true"


# ── State helpers ──────────────────────────────────────────────

def _was_recently(state_file: Path, hours: int = 24) -> bool:
    if not state_file.exists():
        return False
    try:
        last = datetime.fromisoformat(state_file.read_text().strip())
        return datetime.now() - last < timedelta(hours=hours)
    except (ValueError, OSError):
        return False


def _mark(state_file: Path):
    state_file.write_text(datetime.now().isoformat())


def record_run(status: str, details: str):
    """Append run result to history for weekly digest."""
    history = []
    if RUN_HISTORY.exists():
        try:
            history = json.loads(RUN_HISTORY.read_text())
        except (json.JSONDecodeError, OSError):
            history = []

    history.append({
        "time": datetime.now().isoformat(),
        "status": status,
        "details": details,
    })

    # Keep only last 7 days of history
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    history = [h for h in history if h["time"] > cutoff]
    RUN_HISTORY.write_text(json.dumps(history, indent=2))


# ── Email ──────────────────────────────────────────────────────

def send_email(subject: str, body: str) -> bool:
    gmail_addr = os.getenv("GMAIL_ADDRESS")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")
    notify_addr = os.getenv("NOTIFY_EMAIL")

    if not all([gmail_addr, gmail_pass, notify_addr]):
        log.error("Email credentials not configured")
        return False

    msg = MIMEMultipart()
    msg["From"] = gmail_addr
    msg["To"] = notify_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_addr, gmail_pass)
            server.send_message(msg)
        log.info(f"Email sent to {notify_addr}")
        return True
    except Exception as e:
        log.error(f"Failed to send email: {e}")
        return False


def send_weekly_digest():
    """Send a weekly summary if it's been 7+ days since last digest."""
    digest_state = STATE_DIR / "last_digest.txt"
    if _was_recently(digest_state, hours=168):  # 7 days
        return

    history = []
    if RUN_HISTORY.exists():
        try:
            history = json.loads(RUN_HISTORY.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    total = len(history)
    blocked = sum(1 for h in history if h["status"] == "blocked")
    success = sum(1 for h in history if h["status"] == "success")
    not_yet = sum(1 for h in history if h["status"] == "not_available")
    errors = sum(1 for h in history if h["status"] == "error")

    subject = "Marriott Checker - Weekly Status Report"
    body = f"""
    <h2>Marriott Availability Checker — Weekly Report</h2>
    <p>Property: <strong>Cleveland Marriott East (CLECE)</strong><br>
    Target dates: <strong>May 12-16, 2027</strong></p>
    <hr>
    <table style="border-collapse:collapse;">
        <tr><td style="padding:4px 12px;">Total checks (7 days):</td><td><strong>{total}</strong></td></tr>
        <tr><td style="padding:4px 12px;">Successful checks:</td><td><strong>{success + not_yet}</strong></td></tr>
        <tr><td style="padding:4px 12px;">Blocked by bot detection:</td><td><strong>{blocked}</strong></td></tr>
        <tr><td style="padding:4px 12px;">Errors:</td><td><strong>{errors}</strong></td></tr>
        <tr><td style="padding:4px 12px;">Availability found:</td><td><strong>{"YES!" if any(h["status"] == "available" for h in history) else "Not yet"}</strong></td></tr>
    </table>
    <hr>
    <p style="color:#666;font-size:12px;">This is an automated weekly digest.
    The checker runs every 2 hours. You'll get an immediate email when rooms open up.</p>
    """
    if send_email(subject, body):
        _mark(digest_state)


# ── Page analysis ──────────────────────────────────────────────

def analyze_calendar(content: str) -> dict:
    content_lower = content.lower()

    if "access denied" in content_lower or len(content) < 3000:
        return {"available": False, "details": "Calendar page blocked by bot detection.", "conclusive": False, "blocked": True}

    has_may_2027 = "may 2027" in content_lower or "2027-05" in content or "2027/05" in content
    log.info(f"Calendar analysis: may_2027_visible={has_may_2027}, page_size={len(content)}")

    if has_may_2027:
        target_dates = ["2027-05-12", "2027-05-13", "2027-05-14", "2027-05-15"]
        dates_found = [d for d in target_dates if d in content]
        return {
            "available": True,
            "details": f"May 2027 is now showing in the calendar! Dates found: {dates_found or 'month visible'}",
            "conclusive": True,
            "blocked": False,
        }
    else:
        return {
            "available": False,
            "details": "May 2027 not yet visible in the booking calendar — dates haven't opened.",
            "conclusive": True,
            "blocked": False,
        }


def analyze_rates(content: str) -> dict:
    content_lower = content.lower()

    if "access denied" in content_lower or len(content) < 3000:
        return {"available": False, "details": "Rate page blocked by bot detection.", "conclusive": False, "blocked": True}

    positive = ["select room", "view rates", "book now", "add to cart", "room type"]
    negative = ["no availability", "sold out", "no rooms available", "dates are not available"]
    future = ["reservations for this hotel can only be made", "cannot be booked more than", "rates are not yet available"]

    found_pos = [s for s in positive if s in content_lower]
    found_neg = [s for s in negative if s in content_lower]
    found_fut = [s for s in future if s in content_lower]

    log.info(f"Rates analysis: positive={found_pos}, negative={found_neg}, future={found_fut}")

    if found_pos and not found_neg and not found_fut:
        return {"available": True, "details": f"Rooms bookable! Signals: {', '.join(found_pos)}", "conclusive": True, "blocked": False}
    elif found_fut or found_neg:
        return {"available": False, "details": f"Not bookable yet. negative={found_neg}, future={found_fut}", "conclusive": True, "blocked": False}

    return {"available": False, "details": "Inconclusive.", "conclusive": False, "blocked": False}


# ── Browser backends ───────────────────────────────────────────

async def check_with_nodriver() -> dict:
    """Local check using undetected Chrome."""
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
        log.info("Loading calendar page...")
        tab = await browser.get(CALENDAR_URL)
        await tab.sleep(10)

        content = await tab.get_content()
        if "akamai" in content.lower() or len(content) < 3000:
            log.info("Waiting for Akamai challenge...")
            await tab.sleep(10)
            content = await tab.get_content()

        (SCRIPT_DIR / "last_calendar.html").write_text(content, encoding="utf-8")
        log.info(f"Calendar page: {len(content)} bytes")

        cal_result = analyze_calendar(content)
        if cal_result["conclusive"] and cal_result["available"]:
            return cal_result

        log.info("Loading rate list page...")
        tab = await browser.get(RATE_URL)
        await tab.sleep(10)
        content = await tab.get_content()

        (SCRIPT_DIR / "last_rates.html").write_text(content, encoding="utf-8")
        log.info(f"Rate page: {len(content)} bytes")

        rate_result = analyze_rates(content)
        if rate_result["conclusive"]:
            return rate_result
        if cal_result["conclusive"]:
            return cal_result

        # If both pages were blocked, report it
        both_blocked = cal_result.get("blocked") and rate_result.get("blocked")
        return {"available": False, "details": "Both pages blocked by bot detection." if both_blocked else "Inconclusive.", "blocked": both_blocked}
    finally:
        try:
            browser.stop()
        except Exception:
            pass


def check_with_curl() -> dict | None:
    """Fast check using curl_cffi with Chrome TLS fingerprint. Returns None if blocked."""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        log.info("curl_cffi not available, skipping")
        return None

    log.info("Trying curl_cffi (fast path)...")
    session = cffi_requests.Session(impersonate="chrome131")

    try:
        # Warm up session
        session.get("https://www.marriott.com", timeout=15)

        # Check calendar
        resp = session.get(CALENDAR_URL, timeout=15)
        content = resp.text
        log.info(f"curl calendar: HTTP {resp.status_code}, {len(content)} bytes")

        cal_result = analyze_calendar(content)
        if cal_result["conclusive"]:
            return cal_result

        # Check rates
        resp = session.get(RATE_URL, timeout=15)
        content = resp.text
        log.info(f"curl rates: HTTP {resp.status_code}, {len(content)} bytes")

        rate_result = analyze_rates(content)
        if rate_result["conclusive"]:
            return rate_result

    except Exception as e:
        log.info(f"curl_cffi failed: {e}")

    log.info("curl_cffi inconclusive, falling back to Playwright")
    return None


def check_with_playwright() -> dict:
    """CI check using Playwright with stealth."""
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        Stealth().apply_stealth_sync(context)
        page = context.new_page()

        try:
            log.info("Loading calendar page (Playwright)...")
            page.goto(CALENDAR_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(15000)
            content = page.content()

            log.info(f"Calendar page: {len(content)} bytes")

            cal_result = analyze_calendar(content)
            if cal_result["conclusive"] and cal_result["available"]:
                return cal_result

            log.info("Loading rate list page (Playwright)...")
            page.goto(RATE_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(15000)
            content = page.content()

            log.info(f"Rate page: {len(content)} bytes")

            rate_result = analyze_rates(content)
            if rate_result["conclusive"]:
                return rate_result
            if cal_result["conclusive"]:
                return cal_result

            both_blocked = cal_result.get("blocked") and rate_result.get("blocked")
            return {"available": False, "details": "Both pages blocked by bot detection." if both_blocked else "Inconclusive.", "blocked": both_blocked}
        finally:
            browser.close()


# ── Main ───────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info(f"Marriott Availability Checker — {'CI' if IS_CI else 'Local'} mode")
    log.info(f"Property: {PROPERTY_CODE} | Dates: {TARGET_CHECKIN} to {TARGET_CHECKOUT}")

    use_nodriver = os.getenv("USE_NODRIVER") == "true" or not IS_CI

    try:
        if use_nodriver:
            result = check_with_curl() or asyncio.run(check_with_nodriver())
        else:
            result = check_with_curl() or check_with_playwright()
    except Exception as e:
        import traceback
        log.error(f"Check failed with exception: {e}\n{traceback.format_exc()}")
        result = {"available": False, "details": f"Exception: {type(e).__name__}: {e}", "blocked": True}

    was_blocked = result.get("blocked", False)

    if result["available"]:
        log.info(f"AVAILABILITY FOUND! {result['details']}")
        record_run("available", result["details"])

        if not _was_recently(AVAIL_STATE, hours=24):
            subject = "Marriott Cleveland East - Rooms OPEN for May 12-16, 2027!"
            body = f"""
            <h2>Hotel Availability Alert</h2>
            <p>Rooms appear to be available at <strong>Cleveland Marriott East</strong>
            for <strong>May 12-16, 2027</strong>!</p>
            <p><strong>Details:</strong> {result['details']}</p>
            <p><a href="{BOOKING_LINK}" style="font-size:18px;font-weight:bold;">Click here to book on Marriott.com</a></p>
            <p><small>Checked at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
            """
            if send_email(subject, body):
                _mark(AVAIL_STATE)
        else:
            log.info("Already notified in the last 24 hours")

    elif was_blocked:
        log.warning(f"BLOCKED: {result['details']}")
        record_run("blocked", result["details"])

        if not _was_recently(BLOCK_STATE, hours=24):
            subject = "Marriott Checker - BLOCKED by bot detection"
            body = f"""
            <h2>Marriott Checker — Blocked</h2>
            <p>The availability checker was <strong>blocked by Marriott's bot detection</strong> (Akamai).</p>
            <p><strong>Details:</strong> {result['details']}</p>
            <p>This may be temporary. The checker will keep trying every 2 hours.
            If this persists for several days, the approach may need to be adjusted.</p>
            <p><small>Checked at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |
            Mode: {'GitHub Actions' if IS_CI else 'Local'}</small></p>
            """
            if send_email(subject, body):
                _mark(BLOCK_STATE)
        else:
            log.info("Already sent block notification in the last 24 hours")

    else:
        log.info(f"Not available yet: {result['details']}")
        record_run("not_available", result["details"])

    # Weekly digest
    send_weekly_digest()

    log.info("Run complete")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
