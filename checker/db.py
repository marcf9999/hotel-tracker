"""Supabase database client for Hotel Tracker."""

import os
from supabase import create_client, Client

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        _client = create_client(url, key)
    return _client


def get_active_hotels() -> list[dict]:
    resp = get_client().table("hotels").select("*").eq("is_active", True).execute()
    return resp.data


def get_email_settings() -> dict | None:
    resp = get_client().table("email_settings").select("*").eq("id", 1).execute()
    return resp.data[0] if resp.data else None


def insert_check_run(hotel_id: str, status: str, details: str,
                     calendar_bytes: int = 0, rates_bytes: int = 0,
                     checker_mode: str = "") -> str:
    resp = get_client().table("check_runs").insert({
        "hotel_id": hotel_id,
        "status": status,
        "details": details,
        "calendar_bytes": calendar_bytes,
        "rates_bytes": rates_bytes,
        "checker_mode": checker_mode,
    }).execute()
    return resp.data[0]["id"]


def insert_night_availability(rows: list[dict]):
    if rows:
        get_client().table("night_availability").insert(rows).execute()
