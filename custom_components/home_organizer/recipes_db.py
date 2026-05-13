# -*- coding: utf-8 -*-
# // [NEW v9.9.0 | 2026-04-18] Purpose: Dedicated SQLite store for cooking
# // recipes. Lives in a separate file (`recipes.db`) from the main
# // home_organizer.db so recipes can be backed up, exported, or shared
# // without dragging the whole inventory along. Schema is intentionally
# // denormalized (JSON blobs for ingredients/steps/timers) -- searching
# // is done by name/tags/language, not by joining on ingredient rows.
# //
# // Public API is all async. Every blocking sqlite call is funnelled
# // through hass.async_add_executor_job so the HA event loop never stalls.

import json
import logging
import os
import sqlite3
import uuid

_LOGGER = logging.getLogger(__name__)


RECIPES_DB_FILE = "home_organizer_recipes.db"
TABLE_NAME = "recipes"


# ==========================================
# CONNECTION
# ==========================================
def _db_path(hass):
    """Always live in /config next to HA's configuration.yaml."""
    return hass.config.path(RECIPES_DB_FILE)


def _get_conn(hass):
    return sqlite3.connect(_db_path(hass), timeout=10.0)


# ==========================================
# SCHEMA
# ==========================================
def _ensure_table(hass):
    conn = None
    try:
        conn = _get_conn(hass)
        c = conn.cursor()
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                name_lower      TEXT NOT NULL,
                language        TEXT NOT NULL DEFAULT 'en',
                ingredients     TEXT NOT NULL DEFAULT '[]',
                steps           TEXT NOT NULL DEFAULT '[]',
                timers          TEXT NOT NULL DEFAULT '[]',
                tags            TEXT NOT NULL DEFAULT '[]',
                source_type     TEXT NOT NULL DEFAULT 'ai_generated',
                notes           TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used_at    TIMESTAMP,
                use_count       INTEGER DEFAULT 0
            )
        """)
        c.execute(
            f"CREATE INDEX IF NOT EXISTS idx_recipes_name_lower "
            f"ON {TABLE_NAME}(name_lower)"
        )
        c.execute(
            f"CREATE INDEX IF NOT EXISTS idx_recipes_lang "
            f"ON {TABLE_NAME}(language)"
        )
        conn.commit()
        _LOGGER.info(
            f"[HO-RECIPES] Table ready at {_db_path(hass)}"
        )
    except Exception as e:
        _LOGGER.error(
            f"[HO-RECIPES] Table init failed: {e}", exc_info=True
        )
    finally:
        if conn:
            conn.close()


async def async_init(hass):
    """Idempotent. Safe to call from async_setup_entry on every boot."""
    await hass.async_add_executor_job(_ensure_table, hass)


# ==========================================
# CRUD: INSERT / UPSERT
# ==========================================
def _upsert_sync(hass, rec):
    conn = None
    try:
        conn = _get_conn(hass)
        c = conn.cursor()

        # Case-insensitive dedupe on name within the same language.
        name_lower = rec["name"].strip().lower()
        c.execute(
            f"SELECT id FROM {TABLE_NAME} "
            f"WHERE name_lower = ? AND language = ? LIMIT 1",
            (name_lower, rec.get("language", "en")),
        )
        row = c.fetchone()

        if row:
            # Update existing recipe in place
            rid = row[0]
            c.execute(
                f"""
                UPDATE {TABLE_NAME} SET
                    name = ?,
                    ingredients = ?,
                    steps = ?,
                    timers = ?,
                    tags = ?,
                    source_type = ?,
                    notes = ?
                WHERE id = ?
                """,
                (
                    rec["name"],
                    json.dumps(rec.get("ingredients") or [], ensure_ascii=False),
                    json.dumps(rec.get("steps") or [], ensure_ascii=False),
                    json.dumps(rec.get("timers") or [], ensure_ascii=False),
                    json.dumps(rec.get("tags") or [], ensure_ascii=False),
                    rec.get("source_type", "ai_generated"),
                    rec.get("notes"),
                    rid,
                ),
            )
            conn.commit()
            return rid, "updated"

        # Create fresh row
        rid = rec.get("id") or uuid.uuid4().hex
        c.execute(
            f"""
            INSERT INTO {TABLE_NAME}
            (id, name, name_lower, language,
             ingredients, steps, timers, tags,
             source_type, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                rec["name"],
                name_lower,
                rec.get("language", "en"),
                json.dumps(rec.get("ingredients") or [], ensure_ascii=False),
                json.dumps(rec.get("steps") or [], ensure_ascii=False),
                json.dumps(rec.get("timers") or [], ensure_ascii=False),
                json.dumps(rec.get("tags") or [], ensure_ascii=False),
                rec.get("source_type", "ai_generated"),
                rec.get("notes"),
            ),
        )
        conn.commit()
        return rid, "inserted"
    except Exception as e:
        _LOGGER.error(f"[HO-RECIPES] upsert failed: {e}", exc_info=True)
        raise
    finally:
        if conn:
            conn.close()


async def async_save(hass, name, ingredients, steps, timers,
                     language="en", tags=None, notes=None,
                     source_type="ai_generated", recipe_id=None):
    """Save (insert or replace) a recipe. Returns (id, action) tuple."""
    rec = {
        "id": recipe_id,
        "name": name.strip(),
        "language": language,
        "ingredients": ingredients or [],
        "steps": steps or [],
        "timers": timers or [],
        "tags": tags or [],
        "notes": notes,
        "source_type": source_type,
    }
    return await hass.async_add_executor_job(_upsert_sync, hass, rec)


# ==========================================
# CRUD: FIND / FETCH
# ==========================================
def _row_to_dict(row):
    if not row:
        return None
    return {
        "id":           row[0],
        "name":         row[1],
        "name_lower":   row[2],
        "language":     row[3],
        "ingredients":  json.loads(row[4] or "[]"),
        "steps":        json.loads(row[5] or "[]"),
        "timers":       json.loads(row[6] or "[]"),
        "tags":         json.loads(row[7] or "[]"),
        "source_type":  row[8],
        "notes":        row[9],
        "created_at":   row[10],
        "last_used_at": row[11],
        "use_count":    row[12],
    }


def _find_by_name_sync(hass, query, language, limit):
    """Find recipes whose name loosely matches `query` (case-insensitive).

    Returns best matches first: exact > startswith > contains.
    """
    conn = None
    try:
        conn = _get_conn(hass)
        c = conn.cursor()
        q = query.strip().lower()
        like_param = f"%{q}%"

        # Exact match first
        c.execute(
            f"SELECT * FROM {TABLE_NAME} "
            f"WHERE name_lower = ? AND language = ? LIMIT 1",
            (q, language),
        )
        exact = c.fetchone()
        results = []
        if exact:
            results.append(_row_to_dict(exact))

        # Then startswith
        c.execute(
            f"SELECT * FROM {TABLE_NAME} "
            f"WHERE name_lower LIKE ? AND language = ? "
            f"AND name_lower != ? "
            f"ORDER BY use_count DESC, last_used_at DESC "
            f"LIMIT ?",
            (f"{q}%", language, q, limit),
        )
        for row in c.fetchall():
            results.append(_row_to_dict(row))

        # Then contains
        if len(results) < limit:
            remaining = limit - len(results)
            already_ids = {r["id"] for r in results}
            c.execute(
                f"SELECT * FROM {TABLE_NAME} "
                f"WHERE name_lower LIKE ? AND language = ? "
                f"ORDER BY use_count DESC, last_used_at DESC "
                f"LIMIT ?",
                (like_param, language, remaining + len(already_ids)),
            )
            for row in c.fetchall():
                d = _row_to_dict(row)
                if d["id"] not in already_ids:
                    results.append(d)
                    if len(results) >= limit:
                        break

        return results[:limit]
    except Exception as e:
        _LOGGER.error(f"[HO-RECIPES] find failed: {e}", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()


async def async_find_by_name(hass, query, language="en", limit=3):
    """Return up to `limit` recipes matching `query` for the given language."""
    if not query or not query.strip():
        return []
    return await hass.async_add_executor_job(
        _find_by_name_sync, hass, query, language, limit
    )


def _get_by_id_sync(hass, recipe_id):
    conn = None
    try:
        conn = _get_conn(hass)
        c = conn.cursor()
        c.execute(f"SELECT * FROM {TABLE_NAME} WHERE id = ? LIMIT 1",
                  (recipe_id,))
        return _row_to_dict(c.fetchone())
    except Exception as e:
        _LOGGER.error(f"[HO-RECIPES] get_by_id failed: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()


async def async_get_by_id(hass, recipe_id):
    return await hass.async_add_executor_job(_get_by_id_sync, hass, recipe_id)


# ==========================================
# USAGE TRACKING
# ==========================================
def _touch_sync(hass, recipe_id):
    conn = None
    try:
        conn = _get_conn(hass)
        c = conn.cursor()
        c.execute(
            f"UPDATE {TABLE_NAME} "
            f"SET use_count = COALESCE(use_count, 0) + 1, "
            f"    last_used_at = CURRENT_TIMESTAMP "
            f"WHERE id = ?",
            (recipe_id,),
        )
        conn.commit()
    except Exception as e:
        _LOGGER.error(f"[HO-RECIPES] touch failed: {e}")
    finally:
        if conn:
            conn.close()


async def async_touch(hass, recipe_id):
    """Bump use_count + last_used_at. Call when the recipe is actually used."""
    await hass.async_add_executor_job(_touch_sync, hass, recipe_id)


# ==========================================
# CRUD: DELETE / LIST
# ==========================================
def _delete_sync(hass, recipe_id):
    conn = None
    try:
        conn = _get_conn(hass)
        c = conn.cursor()
        c.execute(f"DELETE FROM {TABLE_NAME} WHERE id = ?", (recipe_id,))
        conn.commit()
        return c.rowcount
    except Exception as e:
        _LOGGER.error(f"[HO-RECIPES] delete failed: {e}")
        return 0
    finally:
        if conn:
            conn.close()


async def async_delete(hass, recipe_id):
    return await hass.async_add_executor_job(_delete_sync, hass, recipe_id)


def _list_all_sync(hass, language):
    conn = None
    try:
        conn = _get_conn(hass)
        c = conn.cursor()
        if language:
            c.execute(
                f"SELECT * FROM {TABLE_NAME} WHERE language = ? "
                f"ORDER BY last_used_at DESC, created_at DESC",
                (language,),
            )
        else:
            c.execute(
                f"SELECT * FROM {TABLE_NAME} "
                f"ORDER BY last_used_at DESC, created_at DESC"
            )
        return [_row_to_dict(r) for r in c.fetchall()]
    except Exception as e:
        _LOGGER.error(f"[HO-RECIPES] list failed: {e}")
        return []
    finally:
        if conn:
            conn.close()


async def async_list_all(hass, language=None):
    return await hass.async_add_executor_job(_list_all_sync, hass, language)
