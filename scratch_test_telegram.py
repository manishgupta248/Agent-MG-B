"""
Temporary manual verification script for M6-S1 - NOT part of the
permanent test suite.
"""
import threading
import time

from app.core.logging_setup import configure_logging
from app.core.telegram_bot import start_bot, TelegramNotificationChannel

configure_logging()


def send_test_notification_after_delay():
    time.sleep(3)
    channel = TelegramNotificationChannel()
    result = channel.send("M6-S1 Test", "If you see this in Telegram, the notification channel works.")
    print(f"TelegramNotificationChannel.send() returned: {result}")


threading.Thread(target=send_test_notification_after_delay, daemon=True).start()
print("Starting bot - watch Telegram for a test notification in ~3 seconds, then send /start, then Ctrl+C.")
start_bot()