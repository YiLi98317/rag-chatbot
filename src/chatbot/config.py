"""
Backward-compatible config shim.

New code should import from `chatbot.settings`.
Existing code can continue importing `chatbot.config.get_settings()` / `chatbot.config.Settings`.
"""

from chatbot.settings import Settings, get_settings  # noqa: F401
