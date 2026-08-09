"""
Tier 1 regex intent registry (M13-S1): the first and cheapest tier of
the intent-resolution stack (Tier1 regex -> Tier1.5 compound pipelines
-> Tier2 rapidfuzz -> Tier3 LLM single-tool -> Tier4 LangGraph dynamic
planning). Tier 1 exists to handle clearly-phrased, single-action
requests without ever touching an LLM - fast, free, deterministic.

Design decisions (see chat for full reasoning):
  - Patterns are STATIC PYTHON, declared via @intent_pattern stacked
    with @tool directly in each plugin file - not dynamic/DB-backed.
    Patterns are matching logic, not user data; they belong in version
    control next to the tool whose input_schema they must match.
  - Capture groups map to input fields via an EXPLICIT group_mapping
    dict, not directly by name - decouples pattern wording from a
    tool's actual input_schema field names, so schema changes can't
    silently break a pattern that happened to share a group name.
  - Compound-sentence safety (logged lesson from the prior build): if
    input matches patterns belonging to MORE THAN ONE distinct tool,
    resolve_intent() returns AMBIGUOUS rather than guessing - a hard
    requirement, since a wrong guess could route to a MODIFY/DELETE
    tool the user didn't actually mean.
  - resolve_intent() builds all match state in LOCAL variables, never
    mutating a shared/registered IntentPattern object - the Telegram
    bot runs with concurrent_updates=True (M6), so this function can
    be called from multiple threads simultaneously; any shared mutable
    match state would be a real race condition, not a theoretical one.
  - Pattern authors are responsible for avoiding greedy-regex capture
    bugs (another logged lesson) - not auto-detected here, but every
    example pattern in this codebase should use bounded/non-greedy
    quantifiers as house style.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from loguru import logger

from app.core.exceptions import ValidationError
from app.registry.tool_contract import get_registry


@dataclass
class IntentPattern:
    """One registered regex pattern mapped to a tool. Immutable after registration."""
    tool_name: str
    pattern: re.Pattern
    group_mapping: dict[str, str]  # capture group name -> input_schema field name
    raw_pattern: str  # kept for logging/debugging - re.Pattern's repr is noisy


# Populated at import time by @intent_pattern, same lifecycle as
# tool_contract._registry - discovery.py's walk_packages already
# imports every plugin module, so patterns register automatically.
_patterns: list[IntentPattern] = []


def intent_pattern(
    tool_name: str,
    pattern: str,
    group_mapping: Optional[dict[str, str]] = None,
    flags: int = re.IGNORECASE,
) -> Callable:
    """
    Decorator registering a regex pattern for Tier 1 matching. Stack
    with @tool on the same function:

        @tool(name="gmail_search_messages", ...)
        @intent_pattern(
            tool_name="gmail_search_messages",
            pattern=r"search (?:my )?(?:gmail|email|inbox) for (?P<q>.+)",
            group_mapping={"q": "query"},
        )
        def gmail_search_messages(input_data): ...

    tool_name is passed explicitly rather than inferred from @tool, to
    avoid fragile function-identity lookups across two independent
    registries - simple and explicit beats clever here.

    Does not modify or wrap the decorated function - purely registers
    metadata, same philosophy as @tool itself. Multiple @intent_pattern
    decorators may stack on one function for multiple phrasings.
    """
    def decorator(func: Callable) -> Callable:
        compiled = re.compile(pattern, flags)
        mapping = group_mapping if group_mapping is not None else {name: name for name in compiled.groupindex}
        _patterns.append(IntentPattern(
            tool_name=tool_name, pattern=compiled, group_mapping=mapping, raw_pattern=pattern,
        ))
        logger.debug(f"Registered intent pattern for '{tool_name}': {pattern}")
        return func
    return decorator


def get_patterns() -> list[IntentPattern]:
    """Read-only-by-convention accessor for the populated pattern list."""
    return _patterns


def validate_patterns() -> None:
    """
    Confirms every registered pattern's tool_name refers to an
    actually-registered tool. Call once from main.py's boot sequence,
    AFTER discover_tools() has run (both registries must be fully
    populated first) - catches a typo'd tool_name loudly at startup
    rather than as a permanently-unreachable pattern that would
    otherwise silently fall through to a higher tier forever, with no
    visible symptom.
    """
    registry = get_registry()
    unknown = sorted({ip.tool_name for ip in _patterns if ip.tool_name not in registry})
    if unknown:
        raise ValidationError(
            f"Intent pattern(s) registered for unknown tool_name(s): {unknown} - "
            f"check @intent_pattern calls for typos against @tool names"
        )
    distinct_tools = len({ip.tool_name for ip in _patterns})
    logger.info(f"Validated {len(_patterns)} intent pattern(s) across {distinct_tools} tool(s)")


def normalize_text(text: str) -> str:
    """
    Normalizes input before matching - targets the logged lesson
    "normalize smart quotes/stray spaces from mobile input". Mobile
    keyboards (iOS/Android/Telegram's own autocorrect) commonly
    substitute curly quotes for straight ones and leave irregular
    whitespace, either of which can silently break a pattern written
    and tested against straight quotes and single spaces.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text).strip()
    return text


class IntentStatus(str, Enum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"


@dataclass
class IntentResult:
    status: IntentStatus
    tool_name: Optional[str] = None
    input_dict: Optional[dict] = None
    candidates: list[str] = field(default_factory=list)  # populated only when AMBIGUOUS
    matched_text: Optional[str] = None


def resolve_intent(text: str) -> IntentResult:
    """
    Attempts to resolve free-text input to exactly one tool call via
    Tier 1 regex matching.

    Tries every registered pattern against the normalized input,
    collecting at most one match per DISTINCT tool_name (a tool
    matching via more than one of its own patterns still counts as one
    candidate, not a compound match against itself). All match state
    stays in local variables - see module docstring on why nothing
    shared is ever mutated here.

      - Zero distinct tools matched -> NO_MATCH (expected for most
        input; Tier 1 only handles clearly-phrased single-action
        requests, everything else falls through to a higher tier)
      - Exactly one distinct tool matched -> MATCHED, input_dict built
        from that pattern's capture groups via group_mapping
      - More than one distinct tool matched -> AMBIGUOUS, listing every
        candidate - the compound-sentence safety requirement. Never
        guesses; always defers.
    """
    normalized = normalize_text(text)

    # tool_name -> (IntentPattern, re.Match) - purely local, never
    # written back onto any shared registered object.
    matches_by_tool: dict[str, tuple[IntentPattern, re.Match]] = {}

    for ip in _patterns:
        if ip.tool_name in matches_by_tool:
            continue  # already matched via an earlier pattern for this tool
        m = ip.pattern.search(normalized)
        if m:
            matches_by_tool[ip.tool_name] = (ip, m)

    if not matches_by_tool:
        return IntentResult(status=IntentStatus.NO_MATCH)

    if len(matches_by_tool) > 1:
        candidates = sorted(matches_by_tool.keys())
        logger.info(f"Tier 1: compound/ambiguous match - candidates: {candidates}")
        return IntentResult(status=IntentStatus.AMBIGUOUS, candidates=candidates)

    tool_name, (ip, m) = next(iter(matches_by_tool.items()))
    groupdict = m.groupdict()

    input_dict = {}
    for group_name, field_name in ip.group_mapping.items():
        if group_name not in groupdict:
            raise KeyError(
                f"Intent pattern for '{tool_name}' maps capture group '{group_name}' -> "
                f"'{field_name}', but the pattern has no such named group. Check "
                f"group_mapping against the pattern's (?P<...>...) names."
            )
        value = groupdict[group_name]
        if value is not None and isinstance(value, str):
            value = value.strip()
        if value is not None:
            input_dict[field_name] = value

    logger.info(f"Tier 1 matched '{tool_name}', extracted: {input_dict}")
    return IntentResult(
        status=IntentStatus.MATCHED, tool_name=tool_name, input_dict=input_dict,
        matched_text=m.group(0),
    )