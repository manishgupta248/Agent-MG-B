"""
Approval gating for tool calls requiring human confirmation (Section 2:
"every destructive action requires explicit YES/NO confirmation via a
pluggable ApprovalHandler").

Design:
- ApprovalHandler is an abstract interface. Concrete implementations
  decide HOW a human is asked (CLI now, Telegram in M6, possibly a web
  UI later) - call_tool depends only on this interface, never a
  specific channel.
- APPROVAL_POLICY maps PermissionLevel -> whether approval is required.
  A dict, not hardcoded logic, so per-user/per-tool overrides can be
  layered on later without touching call_tool.
- "One batch approval per run" (Section 2) is stubbed here via a simple
  in-memory set of already-approved run_ids. This is NOT the final
  multi-step batch UX - the real version needs a "plan" to show the
  user up front (a set of steps about to run), which doesn't exist
  until the Job Queue (M10) and Workflow Templates (M13). This stub
  only proves "same run_id doesn't re-prompt" - revisit properly then.
"""

from abc import ABC, abstractmethod

from loguru import logger

from app.registry.tool_contract import PermissionLevel

APPROVAL_POLICY: dict[PermissionLevel, bool] = {
    PermissionLevel.READ: False,
    PermissionLevel.MODIFY: True,
    PermissionLevel.DELETE: True,
    PermissionLevel.ADMIN: True,
}


class ApprovalHandler(ABC):
    """Pluggable approval channel - call_tool only depends on this interface."""

    @abstractmethod
    def request_approval(self, tool_name: str, permission: PermissionLevel, input_dict: dict) -> bool:
        """Return True if the human approved this action, False otherwise."""
        raise NotImplementedError


class CLIApprovalHandler(ApprovalHandler):
    """
    Prompts for YES/NO confirmation in the terminal. For local dev/manual
    testing before the Telegram approval channel exists (M6). Blocking -
    acceptable for now since nothing concurrent depends on it yet;
    revisit for a non-blocking variant if the Job Queue (M10) needs one.
    """

    def request_approval(self, tool_name: str, permission: PermissionLevel, input_dict: dict) -> bool:
        print(f"\n[APPROVAL REQUIRED] Tool: {tool_name} (permission={permission.value})")
        print(f"Input: {input_dict}")
        response = input("Approve? [y/N]: ").strip().lower()
        approved = response == "y"
        logger.info(f"CLI approval for '{tool_name}': {'APPROVED' if approved else 'DENIED'}")
        return approved


class AutoApproveHandler(ApprovalHandler):
    """
    Approves everything automatically. STRICTLY for automated tests -
    never wire this in as a default for a real running agent, since it
    defeats the entire approval gate. Logs a warning every time it's
    used so accidental real-deployment use is obvious in the logs.
    """

    def request_approval(self, tool_name: str, permission: PermissionLevel, input_dict: dict) -> bool:
        logger.warning(
            f"AutoApproveHandler auto-approved '{tool_name}' (permission={permission.value}) "
            f"- this handler must never be used in a real deployment"
        )
        return True


class AutoDenyHandler(ApprovalHandler):
    """Denies everything automatically. Used to test the denial path without interactive input."""

    def request_approval(self, tool_name: str, permission: PermissionLevel, input_dict: dict) -> bool:
        logger.info(f"AutoDenyHandler denied '{tool_name}' (permission={permission.value})")
        return False


# In-memory batch-approval tracker (per-run_id). Process-lifetime only -
# resets on restart. See module docstring re: this being a stub.
_approved_runs: set[str] = set()


def is_run_already_approved(run_id: str | None) -> bool:
    return run_id is not None and run_id in _approved_runs


def mark_run_approved(run_id: str | None) -> None:
    if run_id is not None:
        _approved_runs.add(run_id)