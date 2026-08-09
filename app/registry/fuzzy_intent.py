"""
Tier 2 fuzzy intent matching (M13-S3): catches near-miss phrasing that
doesn't cleanly match any Tier 1 regex - typos, reordered words, filler
words, synonyms not covered by a pattern.

Design decision: Tier 2 identifies WHICH tool the input is closest to,
with a confidence score - it does NOT extract input parameters. Fuzzy
string matching has no equivalent to regex capture groups; trying to
bolt on extraction would mean either restricting this tier to
zero-parameter tools only, or returning unreliable guesses. Parameter
extraction is Tier 3's (LLM) job. A caller that gets a MATCHED result
for a tool with required input fields and calls it anyway will get a
clean ValidationError from call_tool's own Pydantic validation - a
safe, loud failure, not a wrong action executed on bad guessed input.

Same ambiguity-safety discipline as Tier 1/1.5: if two distinct tools'
phrases both score close to the best match, this tier refuses to pick
one rather than guessing.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from loguru import logger
from rapidfuzz import fuzz

from app.core.exceptions import ValidationError
from app.registry.intent_registry import normalize_text
from app.registry.tool_contract import get_registry

# Below this score, nothing is considered a match at all.
MATCH_THRESHOLD = 75
# If a second DISTINCT tool's best score is within this margin of the
# top tool's best score, treat the result as ambiguous rather than
# picking the top one - same "never guess" principle as Tier 1/1.5.
AMBIGUOUS_MARGIN = 10


@dataclass
class FuzzyTrigger:
    tool_name: str
    phrase: str


_triggers: list[FuzzyTrigger] = []


def fuzzy_trigger(tool_name: str, phrases: list[str]):
    """
    Decorator registering one or more canonical example phrases for a
    tool - static Python, declared alongside @tool, same lifecycle and
    reasoning as @intent_pattern (M13-S1): this is matching
    configuration, not user data, so it belongs in version control
    next to the tool it describes.
    """
    def decorator(func):
        for phrase in phrases:
            _triggers.append(FuzzyTrigger(tool_name=tool_name, phrase=phrase))
        logger.debug(f"Registered {len(phrases)} fuzzy trigger phrase(s) for '{tool_name}'")
        return func
    return decorator


def get_triggers() -> list[FuzzyTrigger]:
    return _triggers


def validate_fuzzy_triggers() -> None:
    """
    Confirms every registered trigger's tool_name refers to an
    actually-registered tool. Same boot-time safety net as Tier 1's
    validate_patterns() - call from main.py after discover_tools().
    """
    registry = get_registry()
    unknown = sorted({t.tool_name for t in _triggers if t.tool_name not in registry})
    if unknown:
        raise ValidationError(
            f"Fuzzy trigger(s) registered for unknown tool_name(s): {unknown} - "
            f"check @fuzzy_trigger calls for typos against @tool names"
        )
    distinct_tools = len({t.tool_name for t in _triggers})
    logger.info(f"Validated {len(_triggers)} fuzzy trigger phrase(s) across {distinct_tools} tool(s)")


class FuzzyStatus(str, Enum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"


@dataclass
class FuzzyIntentResult:
    status: FuzzyStatus
    tool_name: Optional[str] = None
    score: Optional[float] = None
    matched_phrase: Optional[str] = None
    candidates: list[str] = field(default_factory=list)  # populated only when AMBIGUOUS


def resolve_fuzzy_intent(text: str) -> FuzzyIntentResult:
    """
    Scores normalized input against every registered trigger phrase
    using WRatio - rapidfuzz's general-purpose composite score (blends
    partial-ratio and token-sort-ratio with length-based calibration),
    chosen after token_set_ratio was found during verification to
    score a single-token typo ("schedul" vs "schedule") at only ~61,
    below any reasonable match threshold - token_set_ratio treats
    differing tokens as fully non-matching rather than fuzzy-comparing
    them, so it doesn't tolerate word-level typos well. WRatio handles
    both the typo case (~86) and length-mismatched phrasing
    (short canonical phrase vs a longer real sentence) without
    producing false positives on genuinely unrelated input (~34)

    Takes the BEST score per distinct tool_name (a tool with multiple
    registered phrases only needs one to score well). Below
    MATCH_THRESHOLD -> NO_MATCH. Two distinct tools both scoring close
    to the top -> AMBIGUOUS, refuses to pick. Otherwise -> MATCHED with
    the winning tool and its score.
    """
    normalized = normalize_text(text)

    best_per_tool: dict[str, tuple[float, str]] = {}  # tool_name -> (score, phrase)
    for t in _triggers:
        score = fuzz.WRatio(normalized, t.phrase)
        if t.tool_name not in best_per_tool or score > best_per_tool[t.tool_name][0]:
            best_per_tool[t.tool_name] = (score, t.phrase)

    if not best_per_tool:
        return FuzzyIntentResult(status=FuzzyStatus.NO_MATCH)

    ranked = sorted(best_per_tool.items(), key=lambda kv: kv[1][0], reverse=True)
    top_tool, (top_score, top_phrase) = ranked[0]

    if top_score < MATCH_THRESHOLD:
        return FuzzyIntentResult(status=FuzzyStatus.NO_MATCH)

    close_competitors = [tool for tool, (score, _) in ranked[1:] if top_score - score <= AMBIGUOUS_MARGIN]
    if close_competitors:
        candidates = sorted([top_tool] + close_competitors)
        logger.info(f"Tier 2: ambiguous fuzzy match (score~{top_score}) - candidates: {candidates}")
        return FuzzyIntentResult(status=FuzzyStatus.AMBIGUOUS, candidates=candidates)

    logger.info(f"Tier 2 matched '{top_tool}' (score={top_score}, phrase='{top_phrase}')")
    return FuzzyIntentResult(status=FuzzyStatus.MATCHED, tool_name=top_tool, score=top_score, matched_phrase=top_phrase)