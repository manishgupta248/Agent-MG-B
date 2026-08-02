"""
Regression suite for the Notification Framework (M5) - the channel
abstraction, the manager's multi-channel broadcast + isolation
behavior, and the Event Bus wiring from M5-S2.
"""

import pytest

from app.core.notifications import NotificationChannel, NotificationManager
from app.core.event_bus import clear_subscribers, publish
from app.core.notification_wiring import wire_notifications_to_events


class RecordingChannel(NotificationChannel):
    """Test double that records every notification it receives instead of actually sending anywhere."""

    def __init__(self):
        self.received: list[tuple[str, str, dict]] = []

    @property
    def channel_name(self) -> str:
        return "recording"

    def send(self, title: str, message: str, metadata=None) -> bool:
        self.received.append((title, message, metadata))
        return True


@pytest.fixture(autouse=True)
def clean_event_bus():
    clear_subscribers()
    yield
    clear_subscribers()


class TestNotificationChannelAndManager:
    def test_manager_broadcasts_to_registered_channel(self):
        channel = RecordingChannel()
        manager = NotificationManager()
        manager.register_channel(channel)

        results = manager.notify("Title", "Message", metadata={"k": "v"})

        assert results == {"recording": True}
        assert channel.received == [("Title", "Message", {"k": "v"})]

    def test_manager_isolates_broken_channel(self):
        class BrokenChannel(NotificationChannel):
            @property
            def channel_name(self) -> str:
                return "broken"

            def send(self, title, message, metadata=None) -> bool:
                raise RuntimeError("boom")

        working = RecordingChannel()
        manager = NotificationManager()
        manager.register_channel(working)
        manager.register_channel(BrokenChannel())

        results = manager.notify("Title", "Message")

        assert results["recording"] is True
        assert results["broken"] is False
        assert len(working.received) == 1

    def test_manager_with_no_channels_returns_empty_dict(self):
        manager = NotificationManager()
        assert manager.notify("Title", "Message") == {}


class TestEventBusNotificationWiring:
    def test_approval_requested_triggers_notification(self):
        from app.core.notifications import notification_manager

        channel = RecordingChannel()
        notification_manager.register_channel(channel)
        try:
            wire_notifications_to_events()
            publish("tool.approval_requested", {"tool_name": "example_modify", "permission": "modify"})

            assert len(channel.received) == 1
            assert "Approval Required" in channel.received[0][0]
            assert "example_modify" in channel.received[0][1]
        finally:
            notification_manager._channels.remove(channel)

    def test_tool_failed_triggers_notification(self):
        from app.core.notifications import notification_manager

        channel = RecordingChannel()
        notification_manager.register_channel(channel)
        try:
            wire_notifications_to_events()
            publish("tool.failed", {"tool_name": "some_tool", "error": "disk full"})

            assert len(channel.received) == 1
            assert "Tool Execution Failed" in channel.received[0][0]
            assert "disk full" in channel.received[0][1]
        finally:
            notification_manager._channels.remove(channel)

    def test_tool_succeeded_does_not_trigger_notification(self):
        from app.core.notifications import notification_manager

        channel = RecordingChannel()
        notification_manager.register_channel(channel)
        try:
            wire_notifications_to_events()
            publish("tool.succeeded", {"tool_name": "example_ping", "result": {}})

            assert len(channel.received) == 0, "tool.succeeded must NOT trigger a notification - too noisy"
        finally:
            notification_manager._channels.remove(channel)