"""
Shared pytest fixtures. Per the documented lesson from the prior build,
any fixture providing database access must call init_db() itself - never
assume schema already exists just because some other test or main.py
happened to run first.
"""

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """
    Points settings.db_path at a temp file for the duration of one test,
    and initializes the schema fresh. Keeps test runs from touching or
    depending on the real data/agent.db.
    """
    from app.core.config import settings
    from app.core.database import init_db

    test_db_path = tmp_path / "test_agent.db"
    monkeypatch.setattr(settings, "db_path", str(test_db_path))
    init_db()
    yield test_db_path


@pytest.fixture(autouse=True)
def ensure_tools_discovered():
    """
    Guarantees the plugin registry is populated before any test runs.
    Safe to call every test - re-importing an already-imported module is
    a no-op for its top-level code, so @tool decorators don't re-fire.
    """
    from app.registry.discovery import discover_tools

    discover_tools()