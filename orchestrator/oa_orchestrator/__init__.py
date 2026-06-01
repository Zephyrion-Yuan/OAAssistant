"""Python LangGraph orchestration layer for OAAssistant.

The deterministic Node/Playwright service stays the "hand"; this package is the
"brain": natural-language intake, slot-filling, PDM cross-system enrichment, and
self-healing execution via a device-agnostic Executor contract.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
