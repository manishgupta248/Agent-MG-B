"""
Regression suite for the Central Knowledge Base (M4): the underlying
data layer (app.core.knowledge_base) plus the @tool wrappers that
expose it to the agent (plugins/knowledge/notes.py), invoked via
call_tool exactly as any tier would.
"""

import pytest

from app.core.knowledge_base import (
    init_knowledge_base,
    add_knowledge_item,
    get_knowledge_item,
    delete_knowledge_item,
)
from app.core.call_tool import call_tool
from app.core.approval import AutoApproveHandler
from app.core.exceptions import ValidationError, ToolExecutionError


@pytest.fixture
def kb(isolated_db):
    """Knowledge base schema, on top of the isolated test DB."""
    init_knowledge_base()
    yield


class TestKnowledgeBaseDataLayer:
    def test_add_and_get(self, kb):
        item_id = add_knowledge_item("note", "hello world")
        item = get_knowledge_item(item_id)
        assert item["content"] == "hello world"
        assert item["content_type"] == "note"
        assert item["embedding"] is None

    def test_invalid_content_type_raises(self, kb):
        with pytest.raises(ValidationError):
            add_knowledge_item("bogus_type", "content")

    def test_delete_removes_item(self, kb):
        item_id = add_knowledge_item("note", "to be deleted")
        assert delete_knowledge_item(item_id) is True
        assert get_knowledge_item(item_id) is None

    def test_delete_nonexistent_returns_false(self, kb):
        assert delete_knowledge_item(999999) is False


class TestKnowledgeBaseTools:
    """Same operations, but through call_tool - proves the @tool wrappers
    and permission levels are wired correctly, not just the data layer."""

    def test_add_knowledge_item_requires_approval(self, kb):
        # MODIFY permission - must fail without a handler.
        with pytest.raises(ToolExecutionError):
            call_tool("add_knowledge_item", {"content_type": "note", "content": "x"})

    def test_add_and_search_via_tools(self, kb):
        result = call_tool(
            "add_knowledge_item",
            {"content_type": "note", "content": "the quick brown fox"},
            approval_handler=AutoApproveHandler(),
        )
        assert result.success is True
        item_id = result.data["id"]

        search_result = call_tool("search_knowledge", {"query": "brown"})
        assert search_result.success is True
        assert any(item["id"] == item_id for item in search_result.data)

    def test_delete_requires_approval(self, kb):
        add_result = call_tool(
            "add_knowledge_item",
            {"content_type": "note", "content": "to delete"},
            approval_handler=AutoApproveHandler(),
        )
        item_id = add_result.data["id"]

        with pytest.raises(ToolExecutionError):
            call_tool("delete_knowledge_item", {"item_id": item_id})

        # With approval, it should succeed.
        delete_result = call_tool(
            "delete_knowledge_item", {"item_id": item_id}, approval_handler=AutoApproveHandler()
        )
        assert delete_result.success is True

    def test_get_nonexistent_returns_failed_result_not_exception(self, kb):
        """A missing item is a normal 'not found' - ToolResult(success=False),
        not an exception. Only real execution failures should raise."""
        result = call_tool("get_knowledge_item", {"item_id": 999999})
        assert result.success is False
        assert "999999" in result.error