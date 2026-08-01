"""
Regression suite for the event bus (M3) - basic pub/sub mechanics plus
confirmation that call_tool publishes the right events at the right
points, including the approval-flow events added in M3-S2.
"""

import pytest

from app.core.approval import AutoApproveHandler, AutoDenyHandler
from app.core.call_tool import call_tool
from app.core.event_bus import clear_subscribers, publish, subscribe, unsubscribe
from app.core.exceptions import ToolExecutionError


@pytest.fixture(autouse=True)
def clean_event_bus():
    """Every test in this module starts with a fresh, empty event bus."""
    clear_subscribers()
    yield
    clear_subscribers()


class TestEventBusCore:
    def test_subscriber_receives_published_event(self):
        received = []
        subscribe("test.event", lambda e: received.append(e))

        publish("test.event", {"foo": "bar"})

        assert len(received) == 1
        assert received[0].event_name == "test.event"
        assert received[0].payload == {"foo": "bar"}

    def test_unsubscribe_stops_delivery(self):
        received = []
        handler = lambda e: received.append(e)
        subscribe("test.event", handler)
        unsubscribe("test.event", handler)

        publish("test.event", {})

        assert received == []

    def test_broken_subscriber_does_not_propagate(self):
        def broken(event):
            raise RuntimeError("boom")

        subscribe("test.event", broken)

        # Must not raise.
        publish("test.event", {})

    def test_publish_with_no_subscribers_is_a_noop(self):
        # Must not raise even though nothing is listening.
        publish("nobody.listening", {"any": "payload"})


class TestCallToolEventIntegration:
    def test_success_publishes_tool_succeeded(self, isolated_db):
        events = []
        subscribe("tool.succeeded", lambda e: events.append(e))

        call_tool("example_ping", {"message": "hi"})

        assert len(events) == 1
        assert events[0].payload["tool_name"] == "example_ping"

    def test_unknown_tool_does_not_publish_tool_failed(self, isolated_db):
        events = []
        subscribe("tool.failed", lambda e: events.append(e))

        with pytest.raises(ToolExecutionError):
            call_tool("nonexistent_tool", {})

        assert events == [], "tool.failed should not fire for a tool that never ran"

    def test_approval_requested_fires_only_when_asking(self, isolated_db):
        requested = []
        subscribe("tool.approval_requested", lambda e: requested.append(e))

        call_tool("example_modify", {"value": "x"}, approval_handler=AutoApproveHandler())

        assert len(requested) == 1
        assert requested[0].payload["tool_name"] == "example_modify"

    def test_approval_granted_fires_on_fresh_approval(self, isolated_db):
        granted = []
        subscribe("tool.approval_granted", lambda e: granted.append(e))

        call_tool("example_modify", {"value": "x"}, approval_handler=AutoApproveHandler())

        assert len(granted) == 1
        assert granted[0].payload["batch_reused"] is False

    def test_approval_denied_fires_on_denial(self, isolated_db):
        denied = []
        subscribe("tool.approval_denied", lambda e: denied.append(e))

        with pytest.raises(ToolExecutionError):
            call_tool("example_modify", {"value": "x"}, approval_handler=AutoDenyHandler())

        assert len(denied) == 1

    def test_batch_reuse_publishes_granted_not_requested(self, isolated_db):
        requested = []
        granted = []
        subscribe("tool.approval_requested", lambda e: requested.append(e))
        subscribe("tool.approval_granted", lambda e: granted.append(e))

        run_id = "event-batch-test"
        call_tool("example_modify", {"value": "a"}, run_id=run_id, approval_handler=AutoApproveHandler())
        call_tool("example_modify", {"value": "b"}, run_id=run_id, approval_handler=AutoDenyHandler())

        # Only the FIRST call should have triggered a request (second reused batch approval).
        assert len(requested) == 1
        # BOTH calls should have published approval_granted (first fresh, second via reuse).
        assert len(granted) == 2
        assert granted[0].payload["batch_reused"] is False
        assert granted[1].payload["batch_reused"] is True