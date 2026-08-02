"""
Temporary manual verification script for M6-S2 - NOT part of the
permanent test suite.
"""
import threading
import time

from app.core.logging_setup import configure_logging
from app.registry.discovery import discover_tools
from app.core.telegram_bot import start_bot

configure_logging()
discover_tools()  # <-- populate the registry before anything tries to call_tool


def trigger_approval_after_delay():
    time.sleep(3)
    from app.core.call_tool import call_tool
    from app.core.telegram_approval import TelegramApprovalHandler

    print("Triggering example_modify with TelegramApprovalHandler - check Telegram for the Approve/Deny buttons.")
    try:
        result = call_tool("example_modify", {"value": "telegram approval test"}, approval_handler=TelegramApprovalHandler())
        print(f"call_tool result: success={result.success}, data={result.data}")
    except Exception as e:
        print(f"call_tool raised (expected if you tapped Deny): {e}")


threading.Thread(target=trigger_approval_after_delay, daemon=True).start()
print("Starting bot - in ~3 seconds an approval request will be sent to Telegram. Tap Approve or Deny, then Ctrl+C once you see the result printed.")
start_bot()