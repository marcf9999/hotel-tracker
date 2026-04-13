"""Analyze Marriott HTML pages for availability and per-night pricing."""

import re
import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)


def _parse_date_from_aria(label: str) -> date | None:
    """Parse 'Wed Apr 01 2026' from aria-label."""
    try:
        parts = label.strip().split()
        if len(parts) >= 4:
            from datetime import datetime
            return datetime.strptime(f"{parts[1]} {parts[2]} {parts[3]}", "%b %d %Y").date()
    except (ValueError, IndexError):
        return None
    return None


def parse_night_availability(html: str, checkin: date, checkout: date) -> list[dict]:
    """
    Parse the Marriott calendar HTML for per-night availability and pricing.

    Each calendar cell looks like:
    <div class="DayPicker-Day [DayPicker-Day--disabled]" aria-label="Wed Apr 01 2026" ...>
      <div class="daypicker-cell-custom ...">
        <span class="rate-value">$149</span>  (or similar)
      </div>
    </div>

    Returns list of dicts with: night_date, is_available, price_cents, currency
    """
    results = []
    target_dates = set()
    d = checkin
    while d < checkout:
        target_dates.add(d)
        d += timedelta(days=1)

    # Find all DayPicker-Day cells with their content
    # Pattern: <div class="DayPicker-Day..." aria-label="..." ...>...</div>
    cell_pattern = re.compile(
        r'<div\s+class="DayPicker-Day([^"]*)"[^>]*'
        r'aria-label="([^"]*)"[^>]*'
        r'aria-disabled="(true|false)"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        re.DOTALL
    )

    found_dates = set()
    for m in cell_pattern.finditer(html):
        classes, aria_label, aria_disabled, inner = m.groups()

        parsed_date = _parse_date_from_aria(aria_label)
        if parsed_date is None or parsed_date not in target_dates:
            continue

        found_dates.add(parsed_date)
        is_disabled = "disabled" in classes.lower() or aria_disabled == "true"
        is_available = not is_disabled

        # Try to extract price from inner content
        price_cents = None
        currency = "USD"
        price_match = re.search(r'[\$€£]([\d,]+(?:\.\d{2})?)', inner)
        if price_match:
            price_str = price_match.group(1).replace(",", "")
            try:
                price_cents = int(float(price_str) * 100)
            except ValueError:
                pass
            # Detect currency
            symbol = inner[price_match.start()]
            if symbol == "€":
                currency = "EUR"
            elif symbol == "£":
                currency = "GBP"

        results.append({
            "night_date": parsed_date.isoformat(),
            "is_available": is_available,
            "price_cents": price_cents,
            "currency": currency,
        })

    # For any target dates not found in the HTML, mark as unavailable
    for d in sorted(target_dates - found_dates):
        results.append({
            "night_date": d.isoformat(),
            "is_available": False,
            "price_cents": None,
            "currency": "USD",
        })

    results.sort(key=lambda x: x["night_date"])
    log.info(f"Per-night: {len(results)} nights, "
             f"{sum(1 for r in results if r['is_available'])} available, "
             f"{sum(1 for r in results if r['price_cents'])} with pricing")
    return results


def analyze_calendar(content: str, checkin: date, checkout: date) -> dict:
    """Check if the target month/dates are visible in the calendar."""
    content_lower = content.lower()

    if "access denied" in content_lower or len(content) < 3000:
        return {"available": False, "details": "Calendar page blocked by bot detection.",
                "conclusive": False, "blocked": True}

    target_month = checkin.strftime("%B %Y").lower()  # e.g. "may 2027"
    target_iso = checkin.strftime("%Y-%m")  # e.g. "2027-05"
    has_target = target_month in content_lower or target_iso in content

    log.info(f"Calendar: target_month_visible={has_target}, page_size={len(content)}")

    nights = parse_night_availability(content, checkin, checkout)
    any_available = any(n["is_available"] for n in nights)

    if has_target and any_available:
        avail_dates = [n["night_date"] for n in nights if n["is_available"]]
        priced = [n for n in nights if n["price_cents"]]
        price_summary = ""
        if priced:
            prices = [f"${n['price_cents']/100:.0f}" for n in priced]
            price_summary = f" Prices: {', '.join(prices)}"
        return {"available": True, "nights": nights,
                "details": f"Dates available: {', '.join(avail_dates)}.{price_summary}",
                "conclusive": True, "blocked": False}
    elif has_target:
        return {"available": False, "nights": nights,
                "details": "Target month visible but dates not yet bookable.",
                "conclusive": True, "blocked": False}
    else:
        return {"available": False, "nights": nights,
                "details": f"{checkin.strftime('%B %Y')} not yet visible — dates haven't opened.",
                "conclusive": True, "blocked": False}


def analyze_rates(content: str) -> dict:
    """Analyze the rate list page."""
    content_lower = content.lower()

    if "access denied" in content_lower or len(content) < 3000:
        return {"available": False, "details": "Rate page blocked.",
                "conclusive": False, "blocked": True}

    positive = ["select room", "view rates", "book now", "add to cart", "room type"]
    negative = ["no availability", "sold out", "no rooms available", "dates are not available"]
    future = ["reservations for this hotel can only be made",
              "cannot be booked more than", "rates are not yet available"]

    found_pos = [s for s in positive if s in content_lower]
    found_neg = [s for s in negative if s in content_lower]
    found_fut = [s for s in future if s in content_lower]

    log.info(f"Rates: positive={found_pos}, negative={found_neg}, future={found_fut}")

    if found_pos and not found_neg and not found_fut:
        return {"available": True, "details": f"Rooms bookable! {', '.join(found_pos)}",
                "conclusive": True, "blocked": False}
    elif found_fut or found_neg:
        return {"available": False, "details": f"Not bookable yet. {found_neg + found_fut}",
                "conclusive": True, "blocked": False}

    return {"available": False, "details": "Inconclusive.", "conclusive": False, "blocked": False}
