from app.core.logging_setup import configure_logging
from app.core.database import init_db
from app.core.workflow_templates import (
    init_workflow_templates, create_workflow_template, get_workflow_template,
    get_workflow_template_by_name, list_workflow_templates, delete_workflow_template,
)
from app.core.exceptions import ValidationError
from app.registry.discovery import discover_tools

configure_logging()
init_db()
init_workflow_templates()
discover_tools()

# A real 2-step template: search Drive, then read whatever file the
# search finds - step 2's input chains off step 1's output via $ref,
# and takes a caller-supplied search query via $param.
template_id = create_workflow_template(
    name="drive_search_and_read",
    description="Search Drive for a file matching a query, then read its content",
    parameters=[{"name": "search_query", "description": "Drive query string", "required": True}],
    steps=[
        {"tool_name": "drive_search_files", "input": {"query": {"$param": "search_query"}, "max_results": 1}},
        {"tool_name": "drive_read_file", "input": {"file_id": {"$ref": {"step": 1, "path": ["data", 0, "id"]}}}},
    ],
)
print(f"Created template {template_id}")

template = get_workflow_template(template_id)
print(f"\nFetched by id: {template['name']}, {len(template['steps'])} step(s)")

by_name = get_workflow_template_by_name("drive_search_and_read")
print(f"Fetched by name: id={by_name['id']}")

print(f"\nAll templates: {[t['name'] for t in list_workflow_templates()]}")

# --- Rejection cases ---

try:
    create_workflow_template("bad1", "unregistered tool", [], [{"tool_name": "not_a_real_tool", "input": {}}])
    print("BUG: unregistered tool was accepted!")
except ValidationError as e:
    print(f"\nCorrectly rejected unregistered tool: {e}")

try:
    create_workflow_template(
        "bad2", "dangling ref", [],
        [{"tool_name": "drive_search_files", "input": {"query": {"$ref": {"step": 5, "path": ["x"]}}}}],
    )
    print("BUG: dangling $ref (step 5 doesn't exist) was accepted!")
except ValidationError as e:
    print(f"Correctly rejected dangling $ref: {e}")

try:
    create_workflow_template(
        "bad3", "ref to future step", [],
        [
            {"tool_name": "drive_search_files", "input": {"query": {"$ref": {"step": 2, "path": ["x"]}}}},
            {"tool_name": "drive_search_files", "input": {"query": "literal"}},
        ],
    )
    print("BUG: forward-reference (step 1 referencing step 2) was accepted!")
except ValidationError as e:
    print(f"Correctly rejected forward-reference: {e}")

try:
    create_workflow_template(
        "bad4", "undeclared param", [],  # no parameters declared
        [{"tool_name": "drive_search_files", "input": {"query": {"$param": "nonexistent"}}}],
    )
    print("BUG: undeclared $param was accepted!")
except ValidationError as e:
    print(f"Correctly rejected undeclared $param: {e}")

try:
    create_workflow_template("drive_search_and_read", "duplicate name", [], [{"tool_name": "drive_search_files", "input": {}}])
    print("BUG: duplicate name was accepted!")
except ValidationError as e:
    print(f"Correctly rejected duplicate name: {e}")

# Cleanup
deleted = delete_workflow_template(template_id)
print(f"\nDeleted template {template_id}: {deleted}")
print(f"Remaining templates: {list_workflow_templates()}")

print("\nAll checks passed.")