"""
Simple synchronous, in-process publish/subscribe event bus.

Purpose (Section 4, item 6): lets tools and call_tool publish events
about their activity without knowing who - if anyone - is listening.
The Notification Framework (M5), Job Queue (M10), and Scheduler (M11)
will all subscribe to relevant events here rather than being directly
called by call_tool or by individual tools.

Scope note: this is intentionally NOT a message broker. It's an
in-process dict of event_name -> list of subscriber callables, with
publish() calling each subscriber synchronously and in-order. That's
the right scope for a single-user local agent on 8GB RAM - a real
broker (Redis, etc.) would be unjustified complexity here.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from loguru import logger


@dataclass
class Event:
    """
    Structured event payload. All subscribers receive this same shape
    regardless of what published it, so new event types never require
    changing the bus itself - just documenting the new event_name and
    its expected payload keys.
    """
    event_name: str
    payload: dict
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# event_name -> list of subscriber callables, each taking a single Event arg
_subscribers: dict[str, list[Callable[[Event], None]]] = {}


def subscribe(event_name: str, handler: Callable[[Event], None]) -> None:
    """Register a handler to be called whenever event_name is published."""
    _subscribers.setdefault(event_name, []).append(handler)
    logger.debug(f"Subscribed handler '{handler.__name__}' to event '{event_name}'")


def unsubscribe(event_name: str, handler: Callable[[Event], None]) -> None:
    """Remove a previously registered handler. No-op if not found."""
    handlers = _subscribers.get(event_name, [])
    if handler in handlers:
        handlers.remove(handler)


def publish(event_name: str, payload: dict) -> None:
    """
    Publish an event to all subscribers of event_name, synchronously,
    in registration order.

    A subscriber that raises is logged and skipped - it must never
    prevent other subscribers from running, and must never propagate
    back to the publisher (call_tool, or a tool itself). A broken
    notification handler must not be able to crash a tool call that
    already succeeded.
    """
    event = Event(event_name=event_name, payload=payload)
    handlers = _subscribers.get(event_name, [])

    for handler in handlers:
        try:
            handler(event)
        except Exception as e:
            logger.error(
                f"Event subscriber '{handler.__name__}' raised while handling "
                f"'{event_name}': {e}"
            )


def clear_subscribers() -> None:
    """
    Removes ALL subscribers for ALL events. Test-only utility - lets
    each test start with a clean bus rather than accumulating handlers
    registered by previous tests in the same session.
    """
    _subscribers.clear()