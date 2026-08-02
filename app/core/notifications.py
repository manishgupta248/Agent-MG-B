"""
Notification Framework (Section 4, item 5): channel-abstracted
notification delivery. Telegram (M6) becomes one NotificationChannel
implementation among possible others (email, desktop, WhatsApp) - never
a hardcoded assumption baked into calling code.

Design notes:
- NotificationChannel is a minimal ABC (send(title, message, metadata)).
  Channel-specific richness (buttons, attachments) is expressed through
  optional metadata keys a given channel chooses to interpret, not
  required interface methods every channel must support.
- NotificationManager holds MULTIPLE registered channels and broadcasts
  to all of them. Each channel's send() is wrapped individually - one
  broken channel (e.g. Telegram briefly offline) must never block
  delivery to the others or crash the caller. Same resilience pattern
  as event_bus.publish()'s per-subscriber isolation.
- Calling code (Event Bus wiring in M5-S2, Scheduler in M11, Job Queue
  in M10) depends only on NotificationManager.notify(...) - never on a
  specific channel class. That's the actual decoupling this section
  calls for.
"""

from abc import ABC, abstractmethod
from typing import Optional

from loguru import logger


class NotificationChannel(ABC):
    """
    Minimal interface every notification channel must implement.
    Returns bool (delivery succeeded/failed) rather than raising, so a
    failed send on one channel doesn't require special-casing by the
    manager beyond its existing try/except wrapper - channels are free
    to log their own failure detail before returning False.
    """

    @abstractmethod
    def send(self, title: str, message: str, metadata: Optional[dict] = None) -> bool:
        """Attempt delivery. Return True on success, False on failure."""
        raise NotImplementedError

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Short identifier for logging, e.g. 'console', 'telegram'."""
        raise NotImplementedError


class ConsoleNotificationChannel(NotificationChannel):
    """
    Prints notifications to the console/log. Real, permanent
    implementation - useful standalone for local dev and headless runs
    (e.g. scheduled jobs in M11 with no human watching Telegram), and
    serves as the first proof that the channel abstraction genuinely
    works before Telegram (M6) becomes the second, heavier implementation.
    """

    @property
    def channel_name(self) -> str:
        return "console"

    def send(self, title: str, message: str, metadata: Optional[dict] = None) -> bool:
        try:
            print(f"\n[NOTIFICATION] {title}\n{message}")
            if metadata:
                print(f"  (metadata: {metadata})")
            logger.info(f"Console notification sent: {title}")
            return True
        except Exception as e:
            logger.error(f"ConsoleNotificationChannel failed to send '{title}': {e}")
            return False


class NotificationManager:
    """
    Holds N registered channels and broadcasts to all of them.
    Instantiate with no channels and call register_channel() to build
    up the active set - keeps construction flexible for tests (e.g. a
    manager with zero or one test channel) vs. real usage (console +
    Telegram + whatever comes later, all at once).
    """

    def __init__(self) -> None:
        self._channels: list[NotificationChannel] = []

    def register_channel(self, channel: NotificationChannel) -> None:
        self._channels.append(channel)
        logger.debug(f"Registered notification channel: {channel.channel_name}")

    def notify(self, title: str, message: str, metadata: Optional[dict] = None) -> dict[str, bool]:
        """
        Send to every registered channel. Returns a dict of
        channel_name -> success bool, so callers that care can inspect
        which channels succeeded/failed; callers that don't care can
        ignore the return value entirely.

        A channel raising (not just returning False) is caught here -
        one broken channel must never prevent the others from receiving
        the notification, and must never propagate back to whatever
        triggered the notification in the first place.
        """
        results: dict[str, bool] = {}
        for channel in self._channels:
            try:
                results[channel.channel_name] = channel.send(title, message, metadata)
            except Exception as e:
                logger.error(f"Notification channel '{channel.channel_name}' raised while sending: {e}")
                results[channel.channel_name] = False
        return results


# Module-level singleton, mirroring the pattern of app.core.config's
# `settings` singleton - most callers just want "the" notification
# manager, not to construct their own. Channels are registered onto
# this instance during startup (main.py, updated in M5-S2).
notification_manager = NotificationManager()