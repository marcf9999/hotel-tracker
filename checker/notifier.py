"""Email notification logic."""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

log = logging.getLogger(__name__)


def send_email(subject: str, body: str, to_addr: str | None = None) -> bool:
    gmail_addr = os.getenv("GMAIL_ADDRESS")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")
    notify_addr = to_addr or os.getenv("NOTIFY_EMAIL")

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


def _build_booking_url(hotel: dict) -> str:
    """Build a booking URL for any hotel source."""
    if hotel.get("source") == "airbnb" and hotel.get("booking_url"):
        return (
            f"{hotel['booking_url']}"
            f"?check_in={hotel['checkin_date']}&check_out={hotel['checkout_date']}&adults=1"
        )
    elif hotel.get("source") == "windsurfer" and hotel.get("booking_url"):
        parts = hotel["checkin_date"].split("-")
        parts2 = hotel["checkout_date"].split("-")
        ci = f"{parts[1]}/{parts[2]}/{parts[0]}"
        co = f"{parts2[1]}/{parts2[2]}/{parts2[0]}"
        return f"{hotel['booking_url']}&checkin={ci}&checkout={co}"
    else:
        from .scraper import build_booking_url
        parts = hotel["checkin_date"].split("-")
        parts2 = hotel["checkout_date"].split("-")
        ci = f"{parts[1]}/{parts[2]}/{parts[0]}"
        co = f"{parts2[1]}/{parts2[2]}/{parts2[0]}"
        return build_booking_url(hotel["property_code"], ci, co)


def _status_color(status: str) -> str:
    if status == "available":
        return "#22c55e"
    elif status == "blocked":
        return "#f97316"
    elif status == "error":
        return "#ef4444"
    return "#94a3b8"


def _status_label(status: str) -> str:
    if status == "available":
        return "AVAILABLE"
    elif status == "not_available":
        return "Not Yet"
    elif status == "blocked":
        return "Blocked"
    elif status == "error":
        return "Error"
    return status


def send_summary_email(results: list[dict]):
    """
    Send a single summary email with one line per hotel.
    results is a list of dicts: { hotel, status, details }
    """
    if not results:
        return False

    any_available = any(r["status"] == "available" for r in results)
    any_blocked = any(r["status"] == "blocked" for r in results)

    # Subject line
    if any_available:
        avail_names = [r["hotel"]["hotel_name"] for r in results if r["status"] == "available"]
        subject = f"Hotel Tracker — Available: {', '.join(avail_names)}"
    elif any_blocked:
        subject = "Hotel Tracker — Some checks blocked"
    else:
        subject = "Hotel Tracker — All hotels checked"

    # Build one-line-per-hotel table
    rows = ""
    for r in results:
        hotel = r["hotel"]
        status = r["status"]
        details = r["details"]
        color = _status_color(status)
        label = _status_label(status)
        dates = f"{hotel['checkin_date']} to {hotel['checkout_date']}"
        booking_url = _build_booking_url(hotel)

        rows += (
            f'<tr>'
            f'<td style="padding:6px 12px;"><a href="{booking_url}" style="color:#2563eb;text-decoration:none;">{hotel["hotel_name"]}</a></td>'
            f'<td style="padding:6px 12px;white-space:nowrap;">{dates}</td>'
            f'<td style="padding:6px 12px;color:{color};font-weight:bold;">{label}</td>'
            f'<td style="padding:6px 12px;color:#666;">{details}</td>'
            f'</tr>'
        )

    body = f"""
    <h2>Hotel Tracker — Check Summary</h2>
    <table style="border-collapse:collapse;margin:16px 0;font-size:14px;">
        <tr style="background:#f1f5f9;">
            <th style="padding:6px 12px;text-align:left;">Hotel</th>
            <th style="padding:6px 12px;text-align:left;">Dates</th>
            <th style="padding:6px 12px;text-align:left;">Status</th>
            <th style="padding:6px 12px;text-align:left;">Details</th>
        </tr>
        {rows}
    </table>
    <p style="color:#666;font-size:12px;">Hotel Tracker — checked {len(results)} hotel(s)</p>
    """
    return send_email(subject, body)
