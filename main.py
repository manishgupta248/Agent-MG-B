"""
Real application entry point for the Personal AI Agent.

Boot sequence (order matters):
  1. configure_logging() - so every subsequent step's errors are captured
  2. init_db()            - schema must exist before anything queries it
  3. discover_tools()     - populates the tool registry from plugins/

Each step is allowed to fail loudly and halt startup - no silent
partial-boot state. As new subsystems come online (Job Queue in M10,
Scheduler in M11, the Telegram bot loop in M6), they get added to this
sequence in dependency order, not bolted on arbitrarily.
"""

from loguru import logger

from app.core.logging_setup import configure_logging
from app.core.database import init_db
from app.registry.discovery import discover_tools
from app.core.knowledge_base import init_knowledge_base


def bootstrap() -> None:
    """Run the full startup sequence. Raises on any failure - caller decides what to do next."""
    configure_logging()
    logger.info("Starting Personal AI Agent boot sequence...")

    init_db()
    init_knowledge_base()

    tool_count = discover_tools()
    logger.info(f"Boot sequence complete - {tool_count} tool(s) available")


def main() -> None:
    bootstrap()
    # Real agent loop (Telegram bot, etc.) is not implemented yet - starts at M6.
    raise NotImplementedError(
        "Boot sequence complete, but no agent loop exists yet - see M6 (Telegram integration)."
    )


if __name__ == "__main__":
    main()