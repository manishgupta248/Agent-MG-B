"""
Base exception hierarchy for the Personal AI Agent.

Rule (per project working rules): any `except Exception:` block must log
the error and re-raise it wrapped in one of these domain exceptions —
never a bare `raise` outside the except block, and never swallow silently.

More specific exceptions get added per-domain as that domain is built
(e.g. GoogleAuthError in M9, TelegramError in M6) — they should all
inherit from AgentError so top-level handlers can catch broadly when needed.
"""


class AgentError(Exception):
    """Base class for all custom exceptions raised by this application."""
    pass


class ConfigError(AgentError):
    """Raised when required configuration/environment values are missing or invalid."""
    pass


class ToolExecutionError(AgentError):
    """Raised when a tool (plugin) fails during execution inside call_tool."""
    pass


class DatabaseError(AgentError):
    """Raised when a SQLite operation fails."""
    pass


class ValidationError(AgentError):
    """Raised when input validation fails outside of Pydantic's own validation
    (e.g. a business-rule check Pydantic can't express directly)."""
    pass