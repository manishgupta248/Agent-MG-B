"""
Knowledge base tools - notes/contacts/preferences/memory.
Thin @tool wrappers around app.core.knowledge_base; no business logic
lives here, just input validation shape + delegation.
"""

from typing import Optional

from pydantic import BaseModel, Field

from app.core.knowledge_base import (
    add_knowledge_item,
    delete_knowledge_item,
    get_knowledge_item,
    list_knowledge_items,
    update_knowledge_item,
)
from app.models.tool_result import ToolResult
from app.registry.tool_contract import PermissionLevel, tool


class AddKnowledgeItemInput(BaseModel):
    content_type: str = Field(description="One of: note, contact, preference, memory")
    content: str = Field(description="The text content to store")
    metadata: Optional[dict] = Field(default=None, description="Optional structured extras")


@tool(
    name="add_knowledge_item",
    description="Add a new item (note, contact, preference, or memory) to the knowledge base.",
    permission=PermissionLevel.MODIFY,
    input_schema=AddKnowledgeItemInput,
)
def add_knowledge_item_tool(input_data: AddKnowledgeItemInput) -> ToolResult:
    item_id = add_knowledge_item(input_data.content_type, input_data.content, input_data.metadata)
    return ToolResult(success=True, data={"id": item_id})


class GetKnowledgeItemInput(BaseModel):
    item_id: int = Field(description="The id of the knowledge item to fetch")


@tool(
    name="get_knowledge_item",
    description="Fetch a single knowledge item by its id.",
    permission=PermissionLevel.READ,
    input_schema=GetKnowledgeItemInput,
)
def get_knowledge_item_tool(input_data: GetKnowledgeItemInput) -> ToolResult:
    item = get_knowledge_item(input_data.item_id)
    if item is None:
        return ToolResult(success=False, error=f"No knowledge item found with id {input_data.item_id}")
    return ToolResult(success=True, data=item)


class SearchKnowledgeInput(BaseModel):
    query: str = Field(description="Substring to search for within knowledge item content")
    content_type: Optional[str] = Field(default=None, description="Optionally restrict to one content type")


@tool(
    name="search_knowledge",
    description=(
        "Search the knowledge base for items whose content contains the given text. "
        "Simple substring match for now - NOT semantic search (that arrives in a later milestone "
        "once embeddings are actually populated)."
    ),
    permission=PermissionLevel.READ,
    input_schema=SearchKnowledgeInput,
)
def search_knowledge_tool(input_data: SearchKnowledgeInput) -> ToolResult:
    all_items = list_knowledge_items(content_type=input_data.content_type)
    query_lower = input_data.query.lower()
    matches = [item for item in all_items if query_lower in item["content"].lower()]
    return ToolResult(success=True, data=matches)


class UpdateKnowledgeItemInput(BaseModel):
    item_id: int
    content: Optional[str] = Field(default=None)
    metadata: Optional[dict] = Field(default=None)


@tool(
    name="update_knowledge_item",
    description="Update the content and/or metadata of an existing knowledge item.",
    permission=PermissionLevel.MODIFY,
    input_schema=UpdateKnowledgeItemInput,
)
def update_knowledge_item_tool(input_data: UpdateKnowledgeItemInput) -> ToolResult:
    updated = update_knowledge_item(input_data.item_id, input_data.content, input_data.metadata)
    if not updated:
        return ToolResult(success=False, error=f"No knowledge item found with id {input_data.item_id}")
    return ToolResult(success=True, data={"id": input_data.item_id, "updated": True})


class DeleteKnowledgeItemInput(BaseModel):
    item_id: int


@tool(
    name="delete_knowledge_item",
    description="Permanently delete a knowledge item by id.",
    permission=PermissionLevel.DELETE,
    input_schema=DeleteKnowledgeItemInput,
)
def delete_knowledge_item_tool(input_data: DeleteKnowledgeItemInput) -> ToolResult:
    deleted = delete_knowledge_item(input_data.item_id)
    if not deleted:
        return ToolResult(success=False, error=f"No knowledge item found with id {input_data.item_id}")
    return ToolResult(success=True, data={"id": input_data.item_id, "deleted": True})