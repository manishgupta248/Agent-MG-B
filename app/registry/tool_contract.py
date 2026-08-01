"""
The @tool decorator: the contract every plugin function must satisfy to
be discoverable by the registry.

IMPORTANT: @tool only REGISTERS metadata about a function. It does not
wrap execution, does not call the function, and does not do approval
checks or audit logging - all of that happens in call_tool (M2), which
looks the tool up in this registry and invokes it through a single
shared pipeline. Decoupling "what tools exist" (this file) from "how a
tool call actually runs" (M2) is deliberate.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Type

from pydantic import BaseModel


class PermissionLevel(str, Enum):
    """
    Replaces the old binary requires_approval flag (Section 4, item 7).
    Every tool must declare one of these; approval POLICY per level is
    implemented later (M2), but the declaration itself starts now so no
    tool is ever added without thinking about its permission level.
    """
    READ = "read"        # no side effects, e.g. reading a file, listing emails
    MODIFY = "modify"     # non-destructive writes, e.g. updating a cell, creating a draft
    DELETE = "delete"     # destructive, e.g. deleting a file, sending an email
    ADMIN = "admin"       # config/credential-level operations


@dataclass
class RegisteredTool:
    """Metadata captured about a single tool at decoration time."""
    name: str
    description: str
    permission: PermissionLevel
    input_schema: Type[BaseModel]
    func: Callable


# Module-level registry populated by @tool at import time, read by
# discovery.py after it has imported every plugin module.
_registry: dict[str, RegisteredTool] = {}


def tool(
    name: str,
    description: str,
    permission: PermissionLevel,
    input_schema: Type[BaseModel],
) -> Callable:
    """
    Decorator that registers a plugin function as a callable tool.

    input_schema is REQUIRED (not optional) - this directly encodes a
    documented lesson from the prior build where a tool's Pydantic input
    model existed but was never attached, silently allowing unvalidated
    input through to a live external API. Making it a required positional
    arg here means that class of bug can't happen again by omission.

    Raises ValueError at import time (i.e. at startup, not at call time)
    if a tool with the same name is registered twice - a silent name
    collision between two plugins was never worth allowing.
    """
    def decorator(func: Callable) -> Callable:
        if name in _registry:
            raise ValueError(
                f"Duplicate tool name '{name}' - already registered by "
                f"{_registry[name].func.__module__}.{_registry[name].func.__name__}"
            )
        _registry[name] = RegisteredTool(
            name=name,
            description=description,
            permission=permission,
            input_schema=input_schema,
            func=func,
        )
        return func

    return decorator


def get_registry() -> dict[str, RegisteredTool]:
    """Read-only-by-convention accessor for the populated registry."""
    return _registry