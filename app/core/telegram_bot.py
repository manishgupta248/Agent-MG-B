"""
Telegram bot integration - the Notification Framework's second channel
implementation (Telegram is Section 4's example of "one NotificationChannel
implementation among possible others", not a hardcoded assumption).

Critical lessons from Section 5 applied from this first version, not
retrofitted after hitting them again:
  - concurrent_updates=True set in the builder from day one - a blocking
    handler (the approval-wait flow, arriving in M6-S2) must never be
    able to deadlock against a separate incoming update (e.g. the
    approval button tap itself) needing to be processed concurrently.
  - Only ONE run_polling() call exists in the whole app (in start_bot()).
    TelegramNotificationChannel sends outbound messages via the SAME
    running Application's bot instance - it never opens a second
    connection. Telegram allows only one getUpdates poll per bot token;
    sending a message is a different API call and is always safe
    alongside that one poll, but this channel must never be tempted to
    construct its own separate Bot/Application to "simplify" sending.
  - Sync-to-async bridge detects an already-running event loop and
    dispatches accordingly, rather than a naive asyncio.run() that
    raises RuntimeError when called from inside code already running
    inside an active loop (e.g. Telegram's own handler dispatch).
"""

import asyncio
import threading

from loguru import logger
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from app.core.config import settings
from app.core.exceptions import ConfigError
from app.core.notifications import NotificationChannel
from app.core.telegram_approval import handle_approval_callback
from telegram.ext import CallbackQueryHandler

# Module-level reference to the running Application, set by start_bot().
# TelegramNotificationChannel needs this to send via the SAME bot
# instance/connection that owns the polling loop - never a second one.
_application: Application | None = None

_bot_event_loop: asyncio.AbstractEventLoop | None = None


async def _capture_bot_loop(application: Application) -> None:
    """
    post_init hook - runs once, inside the bot's own event loop, right
    as it starts. Captures a reference to THAT specific loop, since the
    bot's internal HTTP client locks/events are bound to it. Any code
    sending a message from a different thread must schedule onto this
    exact loop, not just "a" loop via asyncio.run().
    """
    global _bot_event_loop
    _bot_event_loop = asyncio.get_running_loop()
    logger.debug("Captured Telegram bot's event loop reference")

def _is_allowed_user(update: Update) -> bool:
    """Every handler checks this FIRST, before any other logic - this is
    a personal agent with filesystem/email/calendar access; no handler
    processes input from anyone but the configured owner."""
    if not settings.telegram_allowed_user_id:
        logger.error("TELEGRAM_ALLOWED_USER_ID is not configured - refusing all Telegram input")
        return False
    return str(update.effective_user.id) == str(settings.telegram_allowed_user_id)


async def _start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed_user(update):
        logger.warning(f"Rejected /start from unauthorized user id={update.effective_user.id}")
        return
    await update.message.reply_text("Personal AI Agent online. (M6-S1: connectivity only, no commands yet.)")
    logger.info(f"Handled /start for authorized user id={update.effective_user.id}")


def build_application() -> Application:
    """
    Constructs the Application with concurrent_updates=True set from
    the very first version - see module docstring.
    """
    if not settings.telegram_bot_token:
        raise ConfigError("TELEGRAM_BOT_TOKEN is not set in .env - cannot start Telegram bot")

    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .concurrent_updates(True)
        .post_init(_capture_bot_loop)
        .build()
    )
    application.add_handler(CommandHandler("start", _start_command))
    application.add_handler(CallbackQueryHandler(handle_approval_callback))
    return application


def start_bot() -> None:
    """
    Starts the single Telegram polling loop for the whole application.
    This is the ONLY place run_polling() is ever called - see module
    docstring re: the one-getUpdates-connection-per-token constraint.
    """
    global _application
    _application = build_application()
    logger.info("Starting Telegram bot polling loop...")
    _application.run_polling(drop_pending_updates=True)


def get_running_application() -> Application:
    """
    Accessor for the single running Application instance, used by
    TelegramNotificationChannel to send via the same bot/connection
    rather than constructing a second one.
    """
    if _application is None:
        raise ConfigError("Telegram Application is not running - start_bot() has not been called")
    return _application


class TelegramNotificationChannel(NotificationChannel):
    """
    Sends notifications via the same running Application's bot instance
    started by start_bot(). Bridges synchronous NotificationChannel.send()
    to python-telegram-bot's async API, detecting an already-running
    event loop (Section 5 lesson) rather than assuming asyncio.run() is
    always safe to call.
    """

    @property
    def channel_name(self) -> str:
        return "telegram"

    def send(self, title: str, message: str, metadata: dict | None = None) -> bool:
        try:
            application = get_running_application()
            text = f"*{title}*\n{message}"
            self._send_sync_bridge(application, text)
            logger.info(f"Telegram notification sent: {title}")
            return True
        except Exception as e:
            logger.error(f"TelegramNotificationChannel failed to send '{title}': {e}")
            return False

    def _send_sync_bridge(self, application: Application, text: str) -> None:
        """
        Runs the async send_message call from synchronous code, ALWAYS
        scheduled onto the bot's own captured event loop - never a
        freshly created one via asyncio.run(). The bot's internal HTTP
        client holds locks/events bound to the specific loop it started
        on; running the coroutine on any other loop (even a legitimately
        "new" one from asyncio.run()) fails with a cross-loop binding
        error, which is exactly what happened before this fix.
        """
        if _bot_event_loop is None:
            raise ConfigError("Telegram bot event loop not captured yet - has start_bot() finished initializing?")

        coro = application.bot.send_message(
            chat_id=settings.telegram_allowed_user_id,
            text=text,
            parse_mode="Markdown",
        )
        future = asyncio.run_coroutine_threadsafe(coro, _bot_event_loop)
        future.result(timeout=10)