"""
Tier 1.5 compound pipeline resolution (M13-S2): handles multi-action
sentences that Tier 1 (intent_registry.py) correctly refuses to guess
at - e.g. "what's on my calendar and then search my email for the
budget report" matches TWO distinct tools' patterns, which Tier 1
reports as AMBIGUOUS rather than picking one. Tier 1.5 is what turns
that AMBIGUOUS result into a genuine multi-step execution, but only
when it can do so with the same "never guess" discipline Tier 1 uses.

Design decisions (see chat for full reasoning):
  - Segment boundaries are CONSERVATIVE: only 'then', 'and then',
    'after that', and commas split a sentence into segments. Bare
    'and' is deliberately NOT a boundary - it's too common inside a
    single legitimate query ("search drive for budget and forecast")
    to safely treat as a sequencing word.
  - ALL-OR-NOTHING resolution: every segment must resolve to exactly
    one clean Tier 1 match, or the whole compound attempt is UNRESOLVED
    and defers to a higher tier. No partial execution of only the
    segments that happened to resolve - same fail-loudly discipline as
    the rest of the project (Job Queue's no-retry, Workflow Templates'
    no-rollback).
  - Execution is AD-HOC, not synthesized into a Workflow Template -
    resolved steps run directly through call_tool with one shared
    run_id (batch approval, same mechanism Workflow Templates uses).
    Not persisted to workflow_runs/workflow_run_steps: those tables'
    audit overhead is justified for NAMED, SAVED, REUSED templates;
    a Tier 1.5 match is transient and call_tool's own
    execution_history (tagged with the shared run_id) already gives
    adequate traceability without duplicating storage for something
    that will essentially never be identically repeated.
"""

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum

from loguru import logger

from app.core.approval import ApprovalHandler
from app.core.call_tool import call_tool
from app.core.exceptions import ToolExecutionError, ValidationError
from app.registry.intent_registry import IntentStatus, normalize_text, resolve_intent

# Deliberately conservative - see module docstring. 'and then' listed
# first for readability; alternation order doesn't actually change
# matching here since each alternative's literal prefix only matches
# at positions where that exact phrase begins.
SEGMENT_BOUNDARY = re.compile(r"\b(?:and then|then|after that)\b|,", re.IGNORECASE)


class CompoundStatus(str, Enum):
    COMPOUND_MATCHED = "compound_matched"  # 2+ segments, every one resolved cleanly
    NOT_COMPOUND = "not_compound"          # fewer than 2 segments - nothing for Tier 1.5 to do
    UNRESOLVED = "unresolved"              # 2+ segments, but at least one didn't resolve cleanly


@dataclass
class CompoundIntentResult:
    status: CompoundStatus
    steps: list[dict] = field(default_factory=list)               # [{"tool_name", "input_dict"}, ...] in order
    segments: list[str] = field(default_factory=list)
    unresolved_segments: list[str] = field(default_factory=list)  # only populated when UNRESOLVED


def resolve_compound_intent(text: str) -> CompoundIntentResult:
    """
    Splits text on conservative sequencing boundaries and attempts to
    resolve each segment independently via Tier 1. Returns
    COMPOUND_MATCHED only if every non-empty segment resolves to
    exactly one clean match - see module docstring on why this is
    all-or-nothing rather than best-effort.
    """
    normalized = normalize_text(text)
    raw_segments = SEGMENT_BOUNDARY.split(normalized)
    segments = [s.strip() for s in raw_segments if s.strip()]

    if len(segments) < 2:
        # Nothing to split on, or splitting produced only one usable
        # piece (e.g. a trailing comma with nothing meaningful after
        # it) - not a compound sentence as far as Tier 1.5 is concerned.
        return CompoundIntentResult(status=CompoundStatus.NOT_COMPOUND, segments=segments)

    steps = []
    unresolved = []
    for segment in segments:
        result = resolve_intent(segment)
        if result.status == IntentStatus.MATCHED:
            steps.append({"tool_name": result.tool_name, "input_dict": result.input_dict or {}})
        else:
            # Covers both NO_MATCH (segment isn't a recognizable
            # action at all) and AMBIGUOUS (segment itself matches
            # multiple tools) - either way, this segment can't be
            # trusted, and per the all-or-nothing rule that fails the
            # WHOLE compound attempt, not just this piece.
            unresolved.append(segment)

    if unresolved:
        logger.info(f"Tier 1.5: compound split produced unresolved segment(s), deferring: {unresolved}")
        return CompoundIntentResult(
            status=CompoundStatus.UNRESOLVED, segments=segments, unresolved_segments=unresolved,
        )

    logger.info(f"Tier 1.5: resolved compound pipeline - {[s['tool_name'] for s in steps]}")
    return CompoundIntentResult(status=CompoundStatus.COMPOUND_MATCHED, steps=steps, segments=segments)


def resolve_intent_or_compound(text: str):
    """
    Orchestrates Tier 1 -> Tier 1.5: tries Tier 1 first; only falls
    through to compound splitting if Tier 1 itself reported AMBIGUOUS
    (2+ distinct tools matched the whole sentence). If Tier 1.5 also
    can't cleanly resolve it, returns Tier 1's original AMBIGUOUS
    result (with its candidate list) rather than Tier 1.5's UNRESOLVED
    - the caller gets the more informative of the two failures.

    Returns either an IntentResult (Tier 1: MATCHED/AMBIGUOUS/NO_MATCH)
    or a CompoundIntentResult (Tier 1.5: COMPOUND_MATCHED) - callers
    must check which type they got via isinstance or by checking which
    status enum is present. Not unified into one result type in this
    step; worth revisiting if a later tier needs a common shape.
    """
    result = resolve_intent(text)
    if result.status == IntentStatus.AMBIGUOUS:
        compound = resolve_compound_intent(text)
        if compound.status == CompoundStatus.COMPOUND_MATCHED:
            return compound
    return result


def execute_compound_pipeline(steps: list[dict], approval_handler: ApprovalHandler | None = None) -> dict:
    """
    Executes a resolved compound pipeline's steps in order via
    call_tool, sharing one run_id across all steps so approval
    batching happens automatically through the same
    is_run_already_approved()/mark_run_approved() mechanism Workflow
    Templates uses - inherited for free, not reimplemented.

    Stops at the first failure, no rollback - same as Workflow
    Templates' execution engine. Not persisted to any dedicated table;
    see module docstring on why call_tool's own execution_history
    (tagged with this run_id) is sufficient traceability here.

    Returns {"run_id", "status", "steps_completed", "error", "results"}.
    """
    run_id = f"compound-{uuid.uuid4().hex[:8]}"
    results = []
    logger.info(f"Compound pipeline {run_id} starting ({len(steps)} step(s))")

    for i, step in enumerate(steps, start=1):
        try:
            result = call_tool(step["tool_name"], step["input_dict"], run_id=run_id, approval_handler=approval_handler)
        except (ToolExecutionError, ValidationError) as e:
            logger.error(f"Compound pipeline {run_id} failed at step {i} ('{step['tool_name']}'): {e}")
            return {
                "run_id": run_id, "status": "failed", "steps_completed": i - 1,
                "error": str(e), "results": results,
            }
        results.append({"tool_name": step["tool_name"], "result": result.model_dump()})
        logger.info(f"Compound pipeline {run_id} step {i} ('{step['tool_name']}') succeeded")

    logger.info(f"Compound pipeline {run_id} succeeded ({len(steps)} step(s))")
    return {"run_id": run_id, "status": "succeeded", "steps_completed": len(steps), "error": None, "results": results}