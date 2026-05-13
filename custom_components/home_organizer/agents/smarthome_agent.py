# -*- coding: utf-8 -*-
# // [MODIFIED v9.8.0 | 2026-05-04] Purpose: Purged all remaining Hebrew text from the news fetch error messages and LLM prompt hints. Fully implemented dynamic localization for news errors using get_strings_for_language.
# // [MODIFIED v9.7.1 | 2026-05-04] Purpose: Added a User-Agent header to the HTTP request to prevent Google News from blocking the script. Also added better error logging.
# // [MODIFIED v9.7.0 | 2026-05-04] Purpose: Fortified the news summary prompt to strictly enforce JSON formatting and added raw-text fallback parsing.
# // [MODIFIED v9.6.0 | 2026-05-04] Purpose: Updated the LLM classifier prompt.
# // [MODIFIED v9.5.0 | 2026-05-04] Purpose: Replaced hardcoded Israel Hayom RSS with global Google News.
# // [MODIFIED v9.4.0 | 2026-05-04] Purpose: Integrated RSS news fetching directly.
# // [MODIFIED v9.3.0 | 2026-05-04] Purpose: Added 'weather' to LIVE_SENSOR_DOMAINS and extracted temperature.
# // [MODIFIED v9.2.0 | 2026-04-30] Purpose: Added 'automation' to ACTIONABLE_DOMAINS.
# // [v9.1.1 | 2026-04-14] Purpose: Localized fallback strings.
# // [v9.0.0 | 2026-04-13] Purpose: Self-contained Smart Home agent.

import logging
import homeassistant.util.dt as dt_util
import xml.etree.ElementTree as ET
import re

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..ai_core.router import safe_smart_router
from ..ai_core.json_utils import safe_parse_json, apply_voice_rules
from ..ai_core.localized_strings import get_strings_for_language

_LOGGER = logging.getLogger(__name__)


# ==========================================
# NEWS FETCHING LOGIC
# ==========================================
async def fetch_global_news(hass, lang_code):
    session = async_get_clientsession(hass)
    news_items = []
    
    rss_map = {
        "he": "https://news.google.com/rss?hl=he&gl=IL&ceid=IL:he",
        "en": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        "fr": "https://news.google.com/rss?hl=fr&gl=FR&ceid=FR:fr",
        "es": "https://news.google.com/rss?hl=es&gl=ES&ceid=ES:es",
        "it": "https://news.google.com/rss?hl=it&gl=IT&ceid=IT:it",
        "ar": "https://news.google.com/rss?hl=ar&gl=AE&ceid=AE:ar",
        "de": "https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de",
        "ru": "https://news.google.com/rss?hl=ru&gl=RU&ceid=RU:ru",
    }
    
    rss_url = rss_map.get(lang_code, rss_map["en"])
    
    # Mimic a standard web browser to avoid 403 Forbidden errors
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        async with session.get(rss_url, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                xml_data = await resp.text()
                root = ET.fromstring(xml_data)
                
                for item in root.findall(".//item")[:5]:
                    title = item.findtext("title", default="").strip()
                    if title:
                        news_items.append(f"- {title}")
            else:
                _LOGGER.error(f"Google News returned HTTP {resp.status}")
    except Exception as e:
        _LOGGER.error(f"Failed to fetch global news: {e}")
        
    return "\n".join(news_items) if news_items else None


# ==========================================
# PROMPT
# ==========================================
def get_smarthome_prompt(target_lang, user_message, ha_entities_str, current_time_str):
    return f"""You are 'Homie', an intelligent Smart Home controller for Home Assistant.

CURRENT DATE & TIME: {current_time_str}

Your job is to translate the user's natural language request into a strict JSON format. You can EXECUTE an action, ANSWER a question, or FETCH NEWS.

{ha_entities_str}

USER REQUEST: "{user_message}"
TARGET LANGUAGE FOR REPLY: "{target_lang}"

CRITICAL INSTRUCTIONS:
1. Determine if the user wants to DO something (e.g., turn on light), KNOW something (e.g., time/weather), or HEAR THE NEWS.
2. If they want to DO something: Select the exact `entity_id` and output intent "execute_ha_service". To run an automation, use ha_domain: "automation" and ha_service: "trigger".
3. If they want to KNOW something: Output intent "reply" based on the CURRENT DATE & TIME or LIVE SENSORS list.
4. If they ask for the news, headlines, or what's happening today (e.g., "news", "headlines"): Output intent "read_news".
5. You MUST return ONLY a raw JSON object. NO markdown formatting outside the JSON.

Output format for ACTIONS:
{{
  "intent": "execute_ha_service",
  "ha_domain": "<domain>",
  "ha_service": "<service>",
  "entity_id": "<exact_entity_id>",
  "reply_message": "<Confirmation message>"
}}

Output format for QUESTIONS:
{{
  "intent": "reply",
  "reply_message": "<Your answer>"
}}

Output format for NEWS:
{{
  "intent": "read_news"
}}

JSON ONLY:"""


# ==========================================
# ENTITY DISCOVERY
# ==========================================
ACTIONABLE_DOMAINS = [
    "light", "switch", "climate", "cover", "fan",
    "media_player", "script", "scene", "automation"
]
LIVE_SENSOR_DOMAINS = ["sensor", "binary_sensor", "weather"]


def _build_ha_entities_str(hass):
    action_devices = []
    live_sensors = []
    registry = er.async_get(hass)

    for state in hass.states.async_all():
        domain = state.domain
        if domain not in ACTIONABLE_DOMAINS and domain not in LIVE_SENSOR_DOMAINS:
            continue

        friendly_name = str(state.attributes.get("friendly_name", state.entity_id))
        aliases_str = ""
        entity_entry = registry.async_get(state.entity_id)
        if entity_entry and getattr(entity_entry, "aliases", None):
            aliases_list = [str(a) for a in entity_entry.aliases if a]
            if aliases_list:
                aliases_str = f", Aliases: {', '.join(aliases_list)}"

        if domain in ACTIONABLE_DOMAINS:
            action_devices.append(
                f"{state.entity_id} (Name: {friendly_name}{aliases_str})"
            )
        else:
            state_val = str(state.state)
            unit = state.attributes.get("unit_of_measurement", "")
            if domain == "weather":
                temp = state.attributes.get("temperature")
                temp_unit = state.attributes.get("temperature_unit", "°C")
                if temp is not None:
                    state_val += f", Temperature: {temp}{temp_unit}"
            unit_str = f" {str(unit)}" if unit and domain != "weather" else ""
            live_sensors.append(
                f"{state.entity_id} (Name: {friendly_name}{aliases_str}, "
                f"State: {state_val}{unit_str})"
            )

    action_devices_str = "\n".join(action_devices) if action_devices else "No actionable devices found."
    live_sensors_str = "\n".join(live_sensors) if live_sensors else "No sensors found."

    return (
        f"--- ACTIONABLE DEVICES (Turn On/Off/Trigger) ---\n{action_devices_str}\n\n"
        f"--- SENSORS & WEATHER (Live Values) ---\n{live_sensors_str}"
    )


# ==========================================
# RUN LOOP
# ==========================================
async def run(hass, entry, messages, target_lang, existing_locs_str,
              loc_hierarchy_map, history_text, last_user_msg, recipe_name,
              is_voice, device_id, user_id, lang_code="en"):

    strings = await get_strings_for_language(hass, entry, lang_code)
    ha_entities_str = _build_ha_entities_str(hass)
    current_time_str = dt_util.now().strftime("%A, %Y-%m-%d %H:%M:%S")
    
    prompt = get_smarthome_prompt(target_lang, last_user_msg, ha_entities_str, current_time_str)

    raw_res, err = await safe_smart_router(
        hass, entry, apply_voice_rules(prompt, is_voice, target_lang)
    )
    if err or not raw_res:
        return f"❌ {strings['smarthome_engine_error']} ({err})"

    parsed = safe_parse_json(raw_res)
    if not parsed:
        return strings["smarthome_parse_error"]

    try:
        intent = parsed.get("intent")
        
        if intent == "read_news":
            news_text = await fetch_global_news(hass, lang_code)
            if not news_text:
                fetch_err = strings.get("news_fetch_error", "Sorry, I could not fetch the news right now.")
                return f"❌ {fetch_err}"
            
            summary_prompt = f"""You are a helpful smart home assistant. 
Create a natural, short, and engaging morning news broadcast in {target_lang} based ONLY on these real headlines:

{news_text}

CRITICAL INSTRUCTIONS:
1. Return ONLY a valid JSON object. Do not wrap in markdown tags like ```json.
2. Escape all quotes and special characters properly.

Format:
{{
  "reply_message": "<your broadcast>"
}}"""
            
            news_res, n_err = await safe_smart_router(hass, entry, summary_prompt)
            if n_err or not news_res:
                engine_err = strings.get("news_engine_error", "Error formulating the news.")
                return f"❌ {engine_err}: {n_err}"
            
            n_parsed = safe_parse_json(news_res)
            
            if n_parsed and "reply_message" in n_parsed:
                return f"📰 {n_parsed['reply_message']}"
            else:
                _LOGGER.warning("News JSON parsing failed, falling back to raw text.")
                clean_raw = re.sub(r'```json\s*|```\s*', '', news_res).strip()
                clean_raw = re.sub(r'^\{\s*"reply_message"\s*:\s*"?|"?\s*\}$', '', clean_raw).strip()
                
                parse_err = strings.get("news_parse_error", "Error formulating the news.")
                return f"📰 {clean_raw}" if clean_raw else f"❌ {parse_err}"

        elif intent == "execute_ha_service":
            domain = parsed.get("ha_domain")
            service = parsed.get("ha_service")
            entity_id = parsed.get("entity_id")
            reply_msg = parsed.get("reply_message", "")

            if domain and service and entity_id:
                await hass.services.async_call(
                    domain, service, {"entity_id": entity_id}, blocking=False
                )
                return f"🏠 {reply_msg}" if reply_msg else "🏠"
            else:
                return strings["smarthome_unknown_device"]
                
        elif intent == "reply":
            return f"🏠 {parsed.get('reply_message', '')}"
            
    except Exception as e:
        _LOGGER.error(f"Homie execution error: {e}")
        return strings["smarthome_parse_error"]

    return strings["smarthome_unsure"]