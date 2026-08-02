"""
Regression suite for the Telegram approval flow (M6) - the parts
testable without a live Telegram connection. Uses a REAL background
event loop (so run_coroutine_threadsafe is genuinely exercised) but a
FAKE Application/bot.send_message - no actual network calls are made.
"""

import asyncio
import threading
import time

import pytest

import app.core.telegram_bot as telegram_bot_module
import app.core.telegram_approval as telegram_approval_module


class FakeBot:
    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        return None  # no-op; we're not asserting on the sent message content here


class FakeApplication:
    def __init__(self):
        self.bot = FakeBot()


@pytest.fixture
def fake_bot_loop(monkeypatch):
    """
    Starts a real asyncio event loop on a background thread (simulating
    the bot's own loop from telegram_bot.start_bot()), and monkeypatches
    telegram_bot's module-level _application/_bot_event_loop so
    TelegramApprovalHandler.request_approval() schedules onto it exactly
    as it would against the real bot.
    """
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    fake_app = FakeApplication()
    monkeypatch.setattr(telegram_bot_module, "_application", fake_app)
    monkeypatch.setattr(telegram_bot_module, "_bot_event_loop", loop)

    yield loop

    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)


class TestTelegramApprovalFlow:
    def test_approval_resolves_true_when_approved(self, fake_bot_loop):
        """Simulates a full approve flow: request_approval() blocks, then
        we resolve it exactly as handle_approval_callback would internally."""
        from app.core.telegram_approval import TelegramApprovalHandler, _pending_approvals
        from app.registry.tool_contract import PermissionLevel

        handler = TelegramApprovalHandler()
        result_holder = {}

        def run_request():
            result_holder["result"] = handler.request_approval(
                "some_tool", PermissionLevel.MODIFY, {"key": "value"}
            )

        thread = threading.Thread(target=run_request)
        thread.start()

        # Wait for the request to actually register itself as pending.
        deadline = time.time() + 2
        while not _pending_approvals and time.time() < deadline:
            time.sleep(0.01)
        assert len(_pending_approvals) == 1, "request_approval should have registered exactly one pending entry"

        request_id = next(iter(_pending_approvals))
        _pending_approvals[request_id]["approved"] = True
        _pending_approvals[request_id]["event"].set()

        thread.join(timeout=5)
        assert result_holder["result"] is True

    def test_approval_resolves_false_when_denied(self, fake_bot_loop):
        from app.core.telegram_approval import TelegramApprovalHandler, _pending_approvals
        from app.registry.tool_contract import PermissionLevel

        handler = TelegramApprovalHandler()
        result_holder = {}

        def run_request():
            result_holder["result"] = handler.request_approval(
                "some_tool", PermissionLevel.DELETE, {"key": "value"}
            )

        thread = threading.Thread(target=run_request)
        thread.start()

        deadline = time.time() + 2
        while not _pending_approvals and time.time() < deadline:
            time.sleep(0.01)

        request_id = next(iter(_pending_approvals))
        _pending_approvals[request_id]["approved"] = False
        _pending_approvals[request_id]["event"].set()

        thread.join(timeout=5)
        assert result_holder["result"] is False

    def test_approval_times_out_to_denied(self, fake_bot_loop, monkeypatch):
        """Nobody responds - should return False after the (shortened, for
        test speed) timeout, not hang forever."""
        monkeypatch.setattr(telegram_approval_module, "APPROVAL_TIMEOUT_SECONDS", 0.3)

        from app.core.telegram_approval import TelegramApprovalHandler
        from app.registry.tool_contract import PermissionLevel

        handler = TelegramApprovalHandler()
        start = time.monotonic()
        result = handler.request_approval("some_tool", PermissionLevel.ADMIN, {})
        elapsed = time.monotonic() - start

        assert result is False
        assert elapsed < 2, "should have timed out quickly, not hung"