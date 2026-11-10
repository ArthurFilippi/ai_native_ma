"""Guarded access to modules that are delivered by other parts of the build."""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve(module: str, attribute: str) -> Any | None:
    """`module.attribute` when it exists, else `None`. A module that is absent, half written or
    fails to import counts as missing, and the caller falls back to a labelled stub."""
    try:
        target = getattr(importlib.import_module(module), attribute, None)
    except ImportError as error:
        logger.info("cannot import %s: %s", module, error)
        return None
    return target
