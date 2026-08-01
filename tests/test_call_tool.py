"""
Regression suite for the call_tool pipeline (M2). Run only at milestone
boundaries, not after every micro-step - main_test.py covers per-step
verification during active development.
"""

import pytest

from app.core.approval import AutoApproveHandler, AutoDenyHandler
from app.core.call_tool import call_tool
from app.core.exceptions import ToolExecutionError, ValidationError


class TestCallToolCore:
    """Basic invocation, lookup, and validation behavior."""

    def test_returns_result_not_none(self, isolated_db):
        result = call_tool("example_ping", {"message": "pytest"})
        assert result is not None
        assert result.success is True
        assert result.data == "pytest"

    def test_unknown_tool_raises(self, isolated_db):
        with pytest.raises(ToolExecutionError):
            call_tool("nonexistent_tool", {})

    def test_invalid_input_raises_before_execution(self, isolated_db):
        with pytest.raises(ValidationError):
            call_tool("example_ping", {"message": {"bad": "type"}})


class TestAuditLogging:
    """Section 2: every call, success or failure, writes to execution_history."""

    def test_audit_row_written_on_success(self, isolated_db):
        from app.core.database import connection

        with connection() as conn:
            before = conn.execute("SELECT COUNT(*) as c FROM execution_history").fetchone()["c"]

        call_tool("example_ping", {"message": "audit"})

        with connection() as conn:
            after = conn.execute("SELECT COUNT(*) as c FROM execution_history").fetchone()["c"]

        assert after == before + 1

    def test_audit_row_written_on_failure(self, isolated_db):
        from app.core.database import connection

        with connection() as conn:
            before = conn.execute("SELECT COUNT(*) as c FROM execution_history").fetchone()["c"]

        with pytest.raises(ToolExecutionError):
            call_tool("nonexistent_tool", {})

        with connection() as conn:
            after = conn.execute("SELECT COUNT(*) as c FROM execution_history").fetchone()["c"]

        assert after == before + 1


class TestApprovalGating:
    """Section 2: destructive actions require explicit approval via a pluggable handler."""

    def test_read_tool_bypasses_approval(self, isolated_db):
        result = call_tool("example_ping", {"message": "no approval needed"})
        assert result.success is True

    def test_modify_tool_requires_handler(self, isolated_db):
        with pytest.raises(ToolExecutionError):
            call_tool("example_modify", {"value": "x"})

    def test_modify_tool_approved_runs(self, isolated_db):
        result = call_tool("example_modify", {"value": "x"}, approval_handler=AutoApproveHandler())
        assert result.success is True

    def test_modify_tool_denied_raises(self, isolated_db):
        with pytest.raises(ToolExecutionError):
            call_tool("example_modify", {"value": "x"}, approval_handler=AutoDenyHandler())

    def test_batch_approval_reused_within_same_run(self, isolated_db):
        run_id = "pytest-batch-run"
        result1 = call_tool("example_modify", {"value": "a"}, run_id=run_id, approval_handler=AutoApproveHandler())
        assert result1.success is True

        # Second call shares run_id but is handed a DENIER - if batch
        # approval works, the denier should never even be consulted.
        result2 = call_tool("example_modify", {"value": "b"}, run_id=run_id, approval_handler=AutoDenyHandler())
        assert result2.success is True