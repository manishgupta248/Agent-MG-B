"""
Integration point between the Event Bus (M3) and the Notification
Framework (M5). This is the ONLY module that knows about both
call_tool's specific event names AND the notification_manager - neither
event_bus.py nor notifications.py import each other or know the other
exists. Tools and call_tool publish generic events with no awareness
that anything is listening for them, per Section 4 item 6.

Only tool.approval_requested and tool.failed are wired to notifications:
- tool.succeeded is deliberately NOT wired - notifying on every single
  successful read would drown out anything that actually needs
  attention.
- tool.approval_granted/denied are NOT wired - the person granting or
  denying already knows the outcome of their own action.
This is a deliberate signal-vs-noise choice, easy to revisit later
(e.g. per-tool notification preferences) but not over-engineered now.
"""

from loguru import logger

from app.core.event_bus import subscribe, Event
from app.core.notifications import notification_manager


def _on_approval_requested(event: Event) -> None:
    tool_name = event.payload.get("tool_name")
    permission = event.payload.get("permission")
    notification_manager.notify(
        title="Approval Required",
        message=f"Tool '{tool_name}' wants to run (permission: {permission}). Awaiting your approval.",
        metadata=event.payload,
    )


def _on_tool_failed(event: Event) -> None:
    tool_name = event.payload.get("tool_name")
    error = event.payload.get("error")
    notification_manager.notify(
        title="Tool Execution Failed",
        message=f"Tool '{tool_name}' failed: {error}",
        metadata=event.payload,
    )


def wire_notifications_to_events() -> None:
    """
    Call once at startup (from main.py's boot sequence) to connect the
    Event Bus to the Notification Framework. Safe to call more than
    once in the same process only if event_bus.clear_subscribers() was
    called between calls (e.g. in tests) - otherwise handlers would
    double-subscribe and fire twice per event.
    """
    subscribe("tool.approval_requested", _on_approval_requested)
    subscribe("tool.failed", _on_tool_failed)
    logger.info("Notification wiring complete - subscribed to tool.approval_requested, tool.failed")