"""
Loguru configuration for the Personal AI Agent.

Call configure_logging() ONCE, at the top of any real entry point
(main.py, main_test.py). Every other module just does:
    from loguru import logger
and uses the already-configured global logger — Loguru's sinks are
process-global, so no logger instance needs to be passed around.
"""

import sys

from loguru import logger

from app.core.config import settings


def configure_logging() -> None:
    """
    Configure Loguru with:
      - a rotating file sink in logs/ (10 MB per file, keep 5 backups, compressed)
      - a console sink for interactive dev use
    Safe to call multiple times (removes prior handlers first) so tests
    that re-import modules don't stack duplicate sinks.
    """
    logger.remove()  # drop Loguru's default stderr handler to avoid duplicate output

    log_file = settings.logs_dir_path / "agent.log"

    logger.add(
        log_file,
        level=settings.log_level,
        rotation="10 MB",
        retention=5,
        compression="zip",
        enqueue=True,  # process-safe writes, important once Job Queue (M10) adds concurrency
        backtrace=True,
        diagnose=(settings.app_env == "development"),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    )

    logger.add(
        sys.stderr,
        level=settings.log_level,
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    )

    logger.info(f"Logging configured — env={settings.app_env}, level={settings.log_level}")