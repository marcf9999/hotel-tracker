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


def send_availability_alert(hotel: dict, details: str, nights: list[dict]):
    """Send an immediate alert when rooms become available."""
    # Build booking URL based on source
    if hotel.get("source") == "airbnb" and hotel.get("booking_url"):
        booking_url = (
            f"{hotel['booking_url']}"
            f"?check_in={hotel['checkin_date']}&checkout={hotel['checkout_date']}&guests=1"
        )
    elif hotel.get("source") == "windsurfer" and hotel.get("booking_url"):
        parts = hotel["checkin_date"].split("-")
        parts2 = hotel["checkout_date"].split("-")
        ci = f"{parts[1]}/{parts[2]}/{parts[0]}"
        co = f"{parts2[1]}/{parts2[2]}/{parts2[0]}"
        booking_url = f"{hotel['booking_url']}&checkin={ci}&checkout={co}"
    else:
        from .scraper import build_booking_url
        parts = hotel["checkin_date"].split("-")
        parts2 = hotel["checkout_date"].split("-")
        ci = f"{parts[1]}/{parts[2]}/{parts[0]}"
        co = f"{parts2[1]}/{parts2[2]}/{parts2[0]}"
        booking_url = build_booking_url(hotel["property_code"], ci, co)

    # Build per-night table
    night_rows = ""
    for n in nights:
        status = "Available" if n["is_available"] else "Not available"
        price = f"${n['price_cents']/100:.0f}" if n.get("price_cents") else "—"
        color = "#22c55e" if n["is_available"] else "#94a3b8"
        night_rows += f'<tr><td>{n["night_date"]}</td><td style="color:{color};font-weight:bold">{status}</td><td>{price}</td></tr>'

    body = f"""
    <h2>Hotel Availability Alert</h2>
    <p><strong>{hotel['hotel_name']}</strong> ({hotel['property_code']})<br>
    <strong>{hotel['checkin_date']} to {hotel['checkout_date']}</strong></p>
    <p>{details}</p>
    <table style="border-collapse:collapse;margin:16px 0;">
        <tr style="background:#f1f5f9;"><th style="padding:6px 12px;text-align:left;">Night</th>
        <th style="padding:6px 12px;">Status</th><th style="padding:6px 12px;">Price</th></tr>
        {night_rows}
    </table>
    <p><a href="{booking_url}" style="font-size:18px;font-weight:bold;color:#2563eb;">Book Now</a></p>
    <p style="color:#666;font-size:12px;">Hotel Tracker</p>
    """
    return send_email(
        f"{hotel['hotel_name']} — Rooms Available {hotel['checkin_date']}!",
        body,
    )


def send_blocked_alert(hotel: dict, details: str):
    body = f"""
    <h2>Hotel Tracker — Blocked</h2>
    <p><strong>{hotel['hotel_name']}</strong> ({hotel['property_code']}) was blocked by bot detection.</p>
    <p>{details}</p>
    <p>The checker will keep trying every 2 hours.</p>
    <p style="color:#666;font-size:12px;">Hotel Tracker</p>
    """
    return send_email(f"Hotel Tracker — Blocked: {hotel['hotel_name']}", body)
