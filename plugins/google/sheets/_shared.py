"""
Shared helpers for Sheets tools. Not a tool module itself.
"""

from googleapiclient.discovery import build

from app.core.google_auth import get_credentials


def get_sheets_service():
    """
    Builds a fresh Sheets API service object using the shared OAuth
    credentials (app.core.google_auth). Same rebuild-per-call pattern
    as Gmail/Drive/Calendar - credentials can refresh mid-session, and
    build() itself is cheap.
    """
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds)