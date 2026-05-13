# -*- coding: utf-8 -*-
# // [v9.0.0 | 2026-04-13] Purpose: Backward compatibility shim. The real
# // implementation now lives in ai_core/ and agents/. This file exists only
# // so that existing imports in __init__.py and conversation.py keep working
# // with zero changes. Do NOT add new logic here.

from .ai_core.router import async_smart_router, safe_smart_router
from .ai_core.dispatcher import (
    async_universal_agent_loop,
    safe_universal_agent_loop,
    determine_explicit_domain,
)

__all__ = [
    "async_smart_router",
    "safe_smart_router",
    "async_universal_agent_loop",
    "safe_universal_agent_loop",
    "determine_explicit_domain",
]
