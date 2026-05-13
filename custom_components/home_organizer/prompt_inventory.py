# -*- coding: utf-8 -*-
# // [v9.0.0 | 2026-04-13] Purpose: Backward compatibility shim for __init__.py
# // which imports get_barcode_prompt and get_invoice_prompt from this module
# // for the barcode-scan and invoice-OCR flows. The real implementations now
# // live inside agents/inventory_agent.py to keep "all inventory prompts in
# // one place". Do NOT add new logic here.

from .agents.inventory_agent import (
    get_barcode_prompt,
    get_invoice_prompt,
    get_agent_prompt,
    get_search_prompt,
)

__all__ = [
    "get_barcode_prompt",
    "get_invoice_prompt",
    "get_agent_prompt",
    "get_search_prompt",
]
