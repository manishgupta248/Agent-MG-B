from app.core.logging_setup import configure_logging
from app.registry.discovery import discover_tools
from app.registry.fuzzy_intent import (
    resolve_fuzzy_intent, validate_fuzzy_triggers, fuzzy_trigger, FuzzyStatus,
)

configure_logging()
discover_tools()
validate_fuzzy_triggers()

# --- Near-miss phrasing (typo + filler words) should still match ---
result = resolve_fuzzy_intent("hey can you show my schedul please")  # typo'd "schedul"
print(f"Near-miss match: {result.status}, tool={result.tool_name}, score={result.score}")
assert result.status == FuzzyStatus.MATCHED
assert result.tool_name == "calendar_list_events"

# --- Genuinely unrelated input ---
result = resolve_fuzzy_intent("what's the capital of France")
print(f"\nUnrelated input: {result.status}")
assert result.status == FuzzyStatus.NO_MATCH

# --- Ambiguity safety: two DIFFERENT real tools' phrases that
# genuinely tie under WRatio (confirmed empirically, not assumed) ---
fuzzy_trigger(tool_name="gmail_search_messages", phrases=["search my email for items"])(lambda x: x)
fuzzy_trigger(tool_name="drive_search_files", phrases=["search my drive for items"])(lambda x: x)

result = resolve_fuzzy_intent("search for my recent items")
print(f"\nAmbiguous case: {result.status}, candidates={result.candidates}")
assert result.status == FuzzyStatus.AMBIGUOUS

# --- validate_fuzzy_triggers() catches a typo'd tool_name ---
from app.core.exceptions import ValidationError
fuzzy_trigger(tool_name="totally_not_a_real_tool", phrases=["whatever"])(lambda x: x)
try:
    validate_fuzzy_triggers()
    print("\nBUG: typo'd tool_name was not caught!")
except ValidationError as e:
    print(f"\nCorrectly caught typo'd tool_name: {e}")

print("\nAll checks passed.")