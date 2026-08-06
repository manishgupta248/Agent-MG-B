"""
Shared helpers for Gmail tools. Not a tool module itself.
"""

from googleapiclient.discovery import build

from app.core.google_auth import get_credentials


def get_gmail_service():
    """
    Builds a fresh Gmail API service object using the shared OAuth
    credentials (app.core.google_auth). No long-lived service cached at
    module level - credentials can refresh mid-session, and rebuilding
    the service object per call is cheap.
    """
    creds = get_credentials()
    return build("gmail", "v1", credentials=creds)