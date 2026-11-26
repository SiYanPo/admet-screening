# -*- coding: utf-8 -*-
"""Local (no-API) ADMET toolkit for the admet-screening skill.

Offline, RDKit-based *approximations* of the six SciMiner tools that the
admet-pkpd skill normally calls through the SciMiner API. No API key, no
credits, no network required.

These are screening-level surrogates, NOT the trained SciMiner models.
"""
from .tools import (
    TOOL_NAMES, TOOL_ALIASES, run_tool, normalize_tool,
    molecular_descriptors, deep_esol, graph_pka, oba, aomp, admet_predictor,
    METHOD, WARNING,
)

__all__ = [
    "TOOL_NAMES", "TOOL_ALIASES", "run_tool", "normalize_tool",
    "molecular_descriptors", "deep_esol", "graph_pka", "oba", "aomp",
    "admet_predictor", "METHOD", "WARNING",
]
__version__ = "1.0.0"
