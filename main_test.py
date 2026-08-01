"""
Fast, per-step manual verification script.
Run this after every implementation step with: python main_test.py
Full pytest suite is reserved for milestone boundaries only.
"""

from app.core.logging_setup import configure_logging
from loguru import logger


def test_config_loads():
    """M1-S2: confirm settings load and required paths resolve correctly."""
    from app.core.config import settings

    assert settings.data_dir_path.exists(), "data_dir_path should exist"
    assert settings.logs_dir_path.exists(), "logs_dir_path should exist"
    print(f"[M1-S2] Config OK — app_env={settings.app_env}, log_level={settings.log_level}")
    print(f"[M1-S2] db_path resolved to: {settings.db_path_resolved}")


def test_logging_writes():
    """M1-S2: confirm logger writes to console and log file without error."""
    logger.debug("Debug-level test message")
    logger.info("Info-level test message")
    logger.warning("Warning-level test message")
    print("[M1-S2] Logging OK — check logs/agent.log for file output")

def test_database_init():
    """M1-S3: confirm init_db() runs cleanly and execution_history table exists."""
    from app.core.database import init_db, connection

    init_db()

    with connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='execution_history'"
        )
        row = cursor.fetchone()
        assert row is not None, "execution_history table should exist after init_db()"

    print("[M1-S3] Database OK - execution_history table confirmed")

def test_plugin_discovery():
    """M1-S4: confirm recursive discovery finds both the top-level AND
    the nested example tool - proves walk_packages actually recurses."""
    from app.registry.discovery import discover_tools
    from app.registry.tool_contract import get_registry

    count = discover_tools()
    registry = get_registry()

    assert "example_ping" in registry, "top-level example tool should be registered"
    assert "example_deep_ping" in registry, "nested example tool should be registered - if missing, recursion is broken"
    print(f"[M1-S4] Registry OK - {count} tool(s) registered: {list(registry.keys())}")

def test_call_tool_success():
    """M2-S1: confirm call_tool successfully invokes a registered tool
    and returns a populated ToolResult - never None."""
    from app.core.call_tool import call_tool

    result = call_tool("example_ping", {"message": "hello M2"})
    assert result is not None, "call_tool must never return None"
    assert result.success is True
    assert result.data == "hello M2"
    print(f"[M2-S1] call_tool success path OK - result={result.data}")


def test_call_tool_unknown_tool():
    """M2-S1: confirm call_tool raises ToolExecutionError for an unregistered tool name."""
    from app.core.call_tool import call_tool
    from app.core.exceptions import ToolExecutionError

    try:
        call_tool("this_tool_does_not_exist", {})
        assert False, "call_tool should have raised for an unknown tool"
    except ToolExecutionError:
        print("[M2-S1] call_tool unknown-tool path OK - raised ToolExecutionError as expected")


def test_call_tool_invalid_input():
    """M2-S1: confirm invalid input is rejected BEFORE the tool function runs
    - directly tests the 'missing input_schema silently allows bad input' lesson."""
    from app.core.call_tool import call_tool
    from app.core.exceptions import ValidationError

    try:
        # example_ping expects `message: str` - passing an int should fail Pydantic validation
        call_tool("example_ping", {"message": {"not": "a string or int-coercible value"}})
        assert False, "call_tool should have raised ValidationError for bad input"
    except ValidationError:
        print("[M2-S1] call_tool input-validation path OK - raised ValidationError as expected")


def test_call_tool_audit_logged():
    """M2-S1: confirm every call_tool invocation writes a row to execution_history,
    regardless of success/failure - the Section 2 'full audit trail' requirement."""
    from app.core.call_tool import call_tool
    from app.core.database import connection

    with connection() as conn:
        before = conn.execute("SELECT COUNT(*) as c FROM execution_history").fetchone()["c"]

    call_tool("example_ping", {"message": "audit check"})

    with connection() as conn:
        after = conn.execute("SELECT COUNT(*) as c FROM execution_history").fetchone()["c"]

    assert after == before + 1, "exactly one execution_history row should be written per call_tool invocation"
    print(f"[M2-S1] Audit logging OK - execution_history grew from {before} to {after}")


def main():
    print("[M1-S1] Scaffold check starting...")
    print("[M1-S1] Scaffold check complete.")

    configure_logging()

    print("\n[M1-S2] Config + Logging checks starting...")
    test_config_loads()
    test_logging_writes()
    print("[M1-S2] Config + Logging checks complete.")

    print("\n[M1-S3] Database checks starting...")
    test_database_init()
    print("[M1-S3] Database checks complete.")

    print("\n[M1-S4] Plugin registry checks starting...")
    test_plugin_discovery()
    print("[M1-S4] Plugin registry checks complete.")

    print("\n[M2-S1] call_tool pipeline checks starting...")
    test_call_tool_success()
    test_call_tool_unknown_tool()
    test_call_tool_invalid_input()
    test_call_tool_audit_logged()
    print("[M2-S1] call_tool pipeline checks complete.")
    
if __name__ == "__main__":
    main()