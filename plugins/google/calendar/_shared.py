"""
Shared helpers for Calendar tools. Not a tool module itself.
"""

from datetime import datetime

from googleapiclient.discovery import build

from app.core.google_auth import get_credentials
from app.core.exceptions import ValidationError

# Default timezone when a caller doesn't specify one. Matches the
# project owner's locale (IST) - override per-call via the timezone
# field on any tool that accepts one.
DEFAULT_TIMEZONE = "Asia/Kolkata"


def get_calendar_service():
    """
    Builds a fresh Calendar API service object using the shared OAuth
    credentials (app.core.google_auth). Same rebuild-per-call pattern
    as Gmail/Drive - credentials can refresh mid-session, and build()
    itself is cheap.
    """
    creds = get_credentials()
    return build("calendar", "v3", credentials=creds)


def build_event_time(value: str, timezone: str, all_day: bool) -> dict:
    """
    Builds the Calendar API's start/end time structure from a caller-
    supplied string. Two shapes depending on all_day:
      - all_day=True:  {"date": "2026-08-10"}              (date only)
      - all_day=False: {"dateTime": "...", "timeZone": ...} (ISO 8601 + tz)

    Validates the string parses before handing it to the API, so a
    malformed datetime fails loudly here with a clear message rather
    than as an opaque 400 error from Google.
    """
    if all_day:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as e:
            raise ValidationError(
                f"all_day=True requires a date in 'YYYY-MM-DD' format, got '{value}': {e}"
            ) from e
        return {"date": value}

    try:
        # fromisoformat accepts "2026-08-10T14:00:00" without requiring
        # an offset, matching the "separate timezone field" design.
        datetime.fromisoformat(value)
    except ValueError as e:
        raise ValidationError(
            f"Expected ISO 8601 datetime (e.g. '2026-08-10T14:00:00'), got '{value}': {e}"
        ) from e

    return {"dateTime": value, "timeZone": timezone}