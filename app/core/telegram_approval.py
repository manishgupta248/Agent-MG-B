"""
Telegram-backed ApprovalHandler (M2's approval interface, second real
implementation after CLIApprovalHandler).

Critical design point (Section 5 deadlock lesson): request_approval()
blocks synchronously on a threading.Event. This MUST be called from a
thread OTHER than the bot's own event-loop thread - if it were called
from inside an async Telegram handler running on that loop, the block
would freeze the entire loop (concurrent_updates=True schedules handler
COROUTINES concurrently on one loop; it does not make a synchronous
blocking call inside one of them safe). No real command routing into
call_tool exists yet (arrives M12+) - this module's scope is proving
the mechanism works when call_tool runs on an ordinary background
thread, which is the pattern real command handlers will need to
replicate (e.g. via asyncio.to_thread) once they call approval-gated
tools directly from within a handler.
"""

import threading
import time
import uuid

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from app.core.approval import ApprovalHandler
from app.core.config import settings
from app.core.exceptions import ConfigError
from app.registry.tool_contract import PermissionLevel

APPROVAL_TIMEOUT_SECONDS = 120

# request_id -> {"event": threading.Event, "approved": bool | None}
_pending_approvals: dict[str, dict] = {}
_pending_lock = threading.Lock()


def _is_allowed_callback_user(update: Update) -> bool:
    if not settings.telegram_allowed_user_id:
        return False
    return str(update.callback_query.from_user.id) == str(settings.telegram_allowed_user_id)


async def handle_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Registered as a CallbackQueryHandler on the bot's Application (see
    telegram_bot.build_application). Runs on the bot's own event loop,
    exactly once per button tap - this is fast and non-blocking, so it
    never itself risks the deadlock scenario; only the WAITING side
    (request_approval, on a different thread) has to be careful.
    """
    query = update.callback_query
    await query.answer()  # acknowledge the tap immediately, per Telegram API expectations

    if not _is_allowed_callback_user(update):
        logger.warning(f"Rejected approval callback from unauthorized user id={query.from_user.id}")
        return

    try:
        action, request_id = query.data.split(":", 1)
    except ValueError:
        logger.error(f"Malformed callback_data received: {query.data}")
        return

    with _pending_lock:
        pending = _pending_approvals.get(request_id)

    if pending is None:
        # Either already resolved (duplicate tap) or timed out and cleaned up.
        await query.edit_message_text(f"{query.message.text}\n\n(This request is no longer pending.)")
        return

    approved = action == "approve"
    pending["approved"] = approved
    pending["event"].set()

    status = "APPROVED" if approved else "DENIED"
    await query.edit_message_text(f"{query.message.text}\n\n{status}")
    logger.info(f"Telegram approval callback resolved: request_id={request_id}, approved={approved}")


class TelegramApprovalHandler(ApprovalHandler):
    """
    Sends an Approve/Deny inline keyboard via Telegram and blocks
    (synchronously, via threading.Event) until a button is tapped or
    APPROVAL_TIMEOUT_SECONDS elapses. MUST be called from a thread other
    than the bot's own event-loop thread - see module docstring.
    """

    def request_approval(self, tool_name: str, permission: PermissionLevel, input_dict: dict) -> bool:
        from app.core.telegram_bot import get_running_application, _bot_event_loop
        import asyncio

        if _bot_event_loop is None:
            raise ConfigError("Telegram bot event loop not captured yet - has start_bot() finished initializing?")

        application = get_running_application()
        request_id = uuid.uuid4().hex
        event = threading.Event()

        with _pending_lock:
            _pending_approvals[request_id] = {"event": event, "approved": None}

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Approve", callback_data=f"approve:{request_id}"),
            InlineKeyboardButton("Deny", callback_data=f"deny:{request_id}"),
        ]])
        text = f"*Approval Required*\nTool: `{tool_name}`\nPermission: `{permission.value}`\nInput: `{input_dict}`"

        coro = application.bot.send_message(
            chat_id=settings.telegram_allowed_user_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        future = asyncio.run_coroutine_threadsafe(coro, _bot_event_loop)
        future.result(timeout=10)  # confirm the message itself sent; this part is fast, not the wait

        logger.info(f"Sent Telegram approval request for '{tool_name}' (request_id={request_id}), waiting up to {APPROVAL_TIMEOUT_SECONDS}s...")

        resolved_in_time = event.wait(timeout=APPROVAL_TIMEOUT_SECONDS)

        with _pending_lock:
            pending = _pending_approvals.pop(request_id, None)

        if not resolved_in_time:
            logger.warning(f"Telegram approval request '{request_id}' timed out after {APPROVAL_TIMEOUT_SECONDS}s - treating as denied")
            return False

        return pending["approved"] is True