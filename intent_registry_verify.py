from app.core.logging_setup import configure_logging
from app.registry.discovery import discover_tools
from app.registry.intent_registry import (
    resolve_intent, validate_patterns, intent_pattern, IntentStatus,
)

configure_logging()
discover_tools()
validate_patterns()

# --- Matched: gmail (specific keyword required) ---
result = resolve_intent("search my email for quarterly report")
print(f"Gmail match: {result.status}, tool={result.tool_name}, input={result.input_dict}")
assert result.status == IntentStatus.MATCHED
assert result.tool_name == "gmail_search_messages"
assert result.input_dict == {"query": "quarterly report"}

# --- Matched: drive (specific keyword required) ---
result = resolve_intent("search my drive for budget spreadsheet")
print(f"\nDrive match: {result.status}, tool={result.tool_name}, input={result.input_dict}")
assert result.status == IntentStatus.MATCHED
assert result.tool_name == "drive_search_files"

# --- Matched: calendar (no capture groups) ---
result = resolve_intent("What's on my calendar")
print(f"\nCalendar match: {result.status}, tool={result.tool_name}, input={result.input_dict}")
assert result.status == IntentStatus.MATCHED
assert result.tool_name == "calendar_list_events"
assert result.input_dict == {}

# --- Normalization: smart quotes + stray whitespace (mobile input) ---
result = resolve_intent("What\u2019s   on my   calendar")  # curly apostrophe + extra spaces
print(f"\nSmart-quote/whitespace match: {result.status}, tool={result.tool_name}")
assert result.status == IntentStatus.MATCHED, "normalization should have handled the curly quote + extra spaces"

# --- No match ---
result = resolve_intent("what's the weather like today")
print(f"\nNo-match case: {result.status}")
assert result.status == IntentStatus.NO_MATCH

# --- Ambiguous: register two deliberately-overlapping TOY patterns
# directly here (not in real plugin files - overly generic patterns
# like these would be bad house style in production code, they're
# only here to safely exercise the ambiguous branch in isolation).
intent_pattern(
    tool_name="gmail_search_messages",
    pattern=r"search for (?P<q>.+)",
    group_mapping={"q": "query"},
)(lambda x: x)
intent_pattern(
    tool_name="drive_search_files",
    pattern=r"search for (?P<q>.+)",
    group_mapping={"q": "query"},
)(lambda x: x)

result = resolve_intent("search for the quarterly report")
print(f"\nAmbiguous case: {result.status}, candidates={result.candidates}")
assert result.status == IntentStatus.AMBIGUOUS
assert set(result.candidates) == {"gmail_search_messages", "drive_search_files"}

# --- validate_patterns() catches a typo'd tool_name ---
from app.core.exceptions import ValidationError
intent_pattern(tool_name="totally_not_a_real_tool", pattern=r"whatever")(lambda x: x)
try:
    validate_patterns()
    print("\nBUG: typo'd tool_name was not caught!")
except ValidationError as e:
    print(f"\nCorrectly caught typo'd tool_name: {e}")

print("\nAll checks passed.")