"""
Fast, per-step manual verification script.
Run this after every implementation step with: python main_test.py
Full pytest suite is reserved for milestone boundaries only.
"""

from app.core.logging_setup import configure_logging
from loguru import logger


def test_config_loads():
    """M1-S2: confirm settings load and required paths resolve correctly."""
    from app.core.config import settings

    assert settings.data_dir_path.exists(), "data_dir_path should exist"
    assert settings.logs_dir_path.exists(), "logs_dir_path should exist"
    print(f"[M1-S2] Config OK — app_env={settings.app_env}, log_level={settings.log_level}")
    print(f"[M1-S2] db_path resolved to: {settings.db_path_resolved}")


def test_logging_writes():
    """M1-S2: confirm logger writes to console and log file without error."""
    logger.debug("Debug-level test message")
    logger.info("Info-level test message")
    logger.warning("Warning-level test message")
    print("[M1-S2] Logging OK — check logs/agent.log for file output")


def main():
    print("[M1-S1] Scaffold check starting...")
    print("[M1-S1] Scaffold check complete.")

    configure_logging()

    print("\n[M1-S2] Config + Logging checks starting...")
    test_config_loads()
    test_logging_writes()
    print("[M1-S2] Config + Logging checks complete.")


if __name__ == "__main__":
    main()