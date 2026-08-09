from app.core.logging_setup import configure_logging
from app.registry.discovery import discover_tools
from app.registry.intent_registry import resolve_intent, validate_patterns, IntentStatus
from app.registry.compound_intent import (
    resolve_compound_intent, resolve_intent_or_compound, execute_compound_pipeline,
    CompoundStatus,
)

configure_logging()
discover_tools()
validate_patterns()

# --- The motivating case: genuinely compound, both segments resolve cleanly ---
text = "what's on my calendar and then search my email for the budget report"

tier1_alone = resolve_intent(text)
print(f"Tier 1 alone on compound sentence: {tier1_alone.status}, candidates={tier1_alone.candidates}")
assert tier1_alone.status == IntentStatus.AMBIGUOUS, "whole-sentence Tier 1 should be ambiguous here"

compound = resolve_compound_intent(text)
print(f"\nTier 1.5 compound split: {compound.status}")
print(f"Segments: {compound.segments}")
print(f"Steps: {compound.steps}")
assert compound.status == CompoundStatus.COMPOUND_MATCHED
assert [s["tool_name"] for s in compound.steps] == ["calendar_list_events", "gmail_search_messages"]

# --- Orchestrator: should reach the same COMPOUND_MATCHED result automatically ---
orchestrated = resolve_intent_or_compound(text)
print(f"\nOrchestrator result: {type(orchestrated).__name__}, status={orchestrated.status}")
assert orchestrated.status == CompoundStatus.COMPOUND_MATCHED

# --- Safety case: comma inside a single query must NOT be wrongly split ---
safety_text = "search my drive for report, budget"
safety_result = resolve_compound_intent(safety_text)
print(f"\nComma-inside-query safety case: {safety_result.status}")
print(f"Segments: {safety_result.segments}")
print(f"Unresolved: {safety_result.unresolved_segments}")
assert safety_result.status == CompoundStatus.UNRESOLVED, (
    "the second fragment 'budget' alone shouldn't resolve to any tool, "
    "so the whole thing must defer rather than run a wrong/partial action"
)

# --- Not compound at all - single segment ---
simple_text = "search my drive for the annual report"
simple_result = resolve_compound_intent(simple_text)
print(f"\nSimple (non-compound) sentence: {simple_result.status}")
assert simple_result.status == CompoundStatus.NOT_COMPOUND

# --- Execute the real compound pipeline end to end ---
exec_result = execute_compound_pipeline(compound.steps)
print(f"\nExecution result: status={exec_result['status']}, steps_completed={exec_result['steps_completed']}")
for r in exec_result["results"]:
    print(f"  {r['tool_name']}: success={r['result']['success']}")
assert exec_result["status"] == "succeeded"
assert exec_result["steps_completed"] == 2

print("\nAll checks passed.")