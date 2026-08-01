"""
Recursive plugin discovery.

Uses pkgutil.walk_packages (NOT iter_modules) specifically because
iter_modules does not recurse into subpackages - a documented bug from
the prior build where tools placed in nested folders (e.g.
plugins/google/gmail/) were silently never registered. walk_packages
recurses arbitrarily deep, so plugins/google/gmail/send.py is discovered
exactly the same way as a top-level plugins/excel/read.py.

discover_tools() just needs to IMPORT every module under plugins/ -
importing a module runs its @tool-decorated functions' decorators,
which is what actually populates the registry in tool_contract.py.
"""

import importlib
import pkgutil

from loguru import logger

import plugins
from app.registry.tool_contract import get_registry


def discover_tools() -> int:
    """
    Recursively import every module under the plugins package, causing
    all @tool decorators within them to fire and populate the registry.

    Returns the number of tools registered (for verification/logging).
    """
    discovered_modules = []

    for module_info in pkgutil.walk_packages(
        path=plugins.__path__,
        prefix=plugins.__name__ + ".",
    ):
        try:
            importlib.import_module(module_info.name)
            discovered_modules.append(module_info.name)
        except Exception as e:
            # A single broken plugin module should not prevent the rest
            # of the app from starting - log loudly and continue.
            logger.error(f"Failed to import plugin module {module_info.name}: {e}")

    registry = get_registry()
    logger.info(
        f"Plugin discovery complete - scanned {len(discovered_modules)} module(s), "
        f"registered {len(registry)} tool(s)"
    )
    return len(registry)