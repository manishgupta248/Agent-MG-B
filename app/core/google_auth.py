"""
Unified Google OAuth (Section 3: "one credentials.json + one token.json"
covering Gmail, Drive, Calendar, and Sheets). Every Google tool
(plugins/google/gmail, drive, calendar, sheets - M9-S2 onward) calls
get_credentials() from here - none of them touch the OAuth flow
directly.

All four services' scopes are requested together from the very first
authorization, even before Drive/Calendar/Sheets tools exist, so
token.json never needs to be regenerated (forcing re-consent) as later
Google tool milestones land.

First run opens a real browser for interactive consent. Every run after
that refreshes silently using the stored refresh token in token.json -
no browser interaction needed unless the refresh token itself is
revoked or expires (rare under normal use).
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from loguru import logger

from app.core.config import PROJECT_ROOT
from app.core.exceptions import ConfigError

# All four services' scopes requested together - see module docstring.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
]

CREDENTIALS_PATH = PROJECT_ROOT / "config" / "credentials.json"
TOKEN_PATH = PROJECT_ROOT / "config" / "token.json"


def get_credentials() -> Credentials:
    """
    Returns a ready-to-use, valid Credentials object. Handles the full
    lifecycle:
      - token.json exists and is valid -> load and return it directly
      - token.json exists but is expired -> refresh silently using the
        stored refresh token, save the refreshed token.json, return it
      - no token.json yet -> run the interactive browser consent flow
        (first run only), save the resulting token.json, return it

    Every Google tool calls this - none of them implement OAuth logic
    themselves.
    """
    if not CREDENTIALS_PATH.exists():
        raise ConfigError(
            f"config/credentials.json not found at {CREDENTIALS_PATH} - "
            f"download it from Google Cloud Console (OAuth client ID, Desktop app type) first"
        )

    creds: Credentials | None = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        logger.info("Google OAuth token expired - refreshing silently...")
        creds.refresh(Request())
        _save_token(creds)
        return creds

    logger.info("No valid Google OAuth token found - starting interactive browser consent flow...")
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds)
    logger.info("Google OAuth consent complete - token.json saved")
    return creds


def _save_token(creds: Credentials) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())