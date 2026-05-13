# -*- coding: utf-8 -*-
"""Constants for the Home Organizer integration."""

DOMAIN = "home_organizer"
# // [MODIFIED v9.5.0 | 2026-04-18] Purpose: Added CONF_TRIGGER_REMINDER and
# // CONF_TRIGGER_CALENDAR so that Reminder + Calendar domains are fully
# // user-configurable from the config flow, matching the pattern of the
# // existing inventory/shopping/cooking/smart_home/stylist triggers.
# // [MODIFIED v9.3.0 | 2026-04-16] Purpose: Added Hugging Face and Fashn.ai
# // to the Stylist VTO provider constants.
VERSION = "9.5.0"

# Configuration Keys
CONF_API_KEY = "api_key"
CONF_DEBUG = "debug_mode"
CONF_USE_AI = "use_ai"

# AI Config (LLM)
CONF_AI_PROVIDER = "ai_provider"
CONF_AI_BASE_URL = "ai_base_url"
CONF_AI_MODEL = "ai_model"

# Storage
CONF_STORAGE_METHOD = "storage_method"
CONF_DELETE_ON_REMOVE = "delete_on_remove"
STORAGE_METHOD_WWW = "www"
STORAGE_METHOD_MEDIA = "media"

# Providers
PROVIDER_GEMINI = "Google Gemini"
PROVIDER_OPENAI = "OpenAI / Local Ollama"
PROVIDER_CLAUDE = "Anthropic Claude"

# Processing Modes
CONF_PROCESSING_MODE = "processing_mode"
MODE_LOCAL_ONLY = "Local Only (100% Ollama)"
MODE_CLOUD_ONLY = "Cloud Only (Gemini/OpenAI API)"
MODE_HYBRID = "Hybrid (Local Voice + Cloud Images)"
CONF_SYNC_GOOGLE_TASKS = "sync_google_tasks"

# Triggers
CONF_TRIGGER_INVENTORY = "trigger_inventory"
CONF_TRIGGER_SHOPPING = "trigger_shopping"
CONF_TRIGGER_COOKING = "trigger_cooking"
CONF_TRIGGER_SMART_HOME = "trigger_smart_home"
CONF_TRIGGER_STYLIST = "trigger_stylist"
# [ADDED v9.5.0] Reminder + Calendar domain triggers
CONF_TRIGGER_REMINDER = "trigger_reminder"
CONF_TRIGGER_CALENDAR = "trigger_calendar"

# Virtual Try-On (VTO) Constants
CONF_USE_STYLIST = "use_stylist"
CONF_VTO_PROVIDER = "vto_provider"
CONF_VTO_URL = "vto_url"
CONF_VTO_KEY = "vto_key"
CONF_VTO_MODEL = "vto_model"

VTO_PROVIDER_FAL = "Fal.ai (Cloud)"
VTO_PROVIDER_COMFYUI = "ComfyUI (Local)"
VTO_PROVIDER_HUGGINGFACE = "Hugging Face (Free Cloud)"
VTO_PROVIDER_FASHN = "Fashn.ai (Cloud)"

# Storage constants
DB_FILE = "home_organizer.db"
IMG_DIR = "home_organizer_images"
