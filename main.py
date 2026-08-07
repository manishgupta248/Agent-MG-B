"""
Real application entry point for the Personal AI Agent.

Boot sequence (order matters):
  1. configure_logging()
  2. init_db()
  3. init_knowledge_base()
  4. discover_tools()
  5. register notification channels + wire to event bus
  6. start_bot() - blocking; the actual agent loop (M6)
"""

from loguru import logger

from app.core.logging_setup import configure_logging
from app.core.database import init_db
from app.core.knowledge_base import init_knowledge_base
from app.registry.discovery import discover_tools
from app.core.notifications import notification_manager, ConsoleNotificationChannel
from app.core.notification_wiring import wire_notifications_to_events
from app.core.telegram_bot import start_bot, TelegramNotificationChannel
from app.core.job_queue import init_job_queue
from app.core.job_worker import start_background_worker
from app.core.scheduler import init_scheduler


def bootstrap() -> None:
    """Run the full startup sequence. Raises on any failure - caller decides what to do next."""
    configure_logging()
    logger.info("Starting Personal AI Agent boot sequence...")

    init_db()
    init_knowledge_base()
    init_job_queue()
    init_scheduler()

    tool_count = discover_tools()
    logger.info(f"Boot sequence complete - {tool_count} tool(s) available")

    notification_manager.register_channel(ConsoleNotificationChannel())
    notification_manager.register_channel(TelegramNotificationChannel())
    wire_notifications_to_events()

    start_background_worker()
    
def main() -> None:
    bootstrap()
    logger.info("Boot sequence complete - starting Telegram bot as the main agent loop.")
    start_bot()  # blocking - this is the real agent loop from here on


if __name__ == "__main__":
    main()