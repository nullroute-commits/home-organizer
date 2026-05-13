# -*- coding: utf-8 -*-
# // [NEW v9.4.0 | 2026-04-18] Purpose: Persistent storage layer for the
# // Reminder + Calendar agents. Every reminder is written here BEFORE any
# // HA-side scheduling occurs so that a crash, reload, or power outage
# // never loses a pending reminder. The table lives in the same SQLite file
# // as the rest of the integration (home_organizer.db).

import logging
import sqlite3
import uuid

from .database import get_db_connection

_LOGGER = logging.getLogger(__name__)

TABLE_NAME = "scheduled_reminders"


# ==========================================
# TABLE INITIALIZATION
# ==========================================
def _ensure_table(hass):
    conn = None
    try:
        conn = get_db_connection(hass)
        c = conn.cursor()
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                id                  TEXT PRIMARY KEY,
                target_timestamp    TEXT NOT NULL,
                message             TEXT NOT NULL,
                device_id           TEXT,
                user_id             TEXT,
                status              TEXT NOT NULL DEFAULT 'pending',
                entry_type          TEXT NOT NULL DEFAULT 'reminder',
                calendar_event_id   TEXT,
                spoken_confirmation TEXT,
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fired_at            TIMESTAMP
            )
        """)
        c.execute(
            f"CREATE INDEX IF NOT EXISTS idx_rem_status "
            f"ON {TABLE_NAME}(status)"
        )
        c.execute(
            f"CREATE INDEX IF NOT EXISTS idx_rem_target "
            f"ON {TABLE_NAME}(target_timestamp)"
        )
        conn.commit()
    except Exception as e:
        _LOGGER.error(f"Reminders table init failed: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()


async def async_init_table(hass):
    """Must be called once during async_setup_entry, before the scheduler."""
    await hass.async_add_executor_job(_ensure_table, hass)


# ==========================================
# CRUD
# ==========================================
def _insert(hass, rec):
    conn = None
    try:
        conn = get_db_connection(hass)
        c = conn.cursor()
        c.execute(
            f"""
            INSERT INTO {TABLE_NAME}
            (id, target_timestamp, message, device_id, user_id,
             status, entry_type, calendar_event_id, spoken_confirmation)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                rec["id"],
                rec["target_timestamp"],
                rec["message"],
                rec.get("device_id"),
                rec.get("user_id"),
                rec.get("entry_type", "reminder"),
                rec.get("calendar_event_id"),
                rec.get("spoken_confirmation"),
            ),
        )
        conn.commit()
    except Exception as e:
        _LOGGER.error(f"Failed to insert reminder: {e}", exc_info=True)
        raise
    finally:
        if conn:
            conn.close()


async def async_insert(hass, target_timestamp, message,
                       device_id=None, user_id=None,
                       entry_type="reminder",
                       calendar_event_id=None,
                       spoken_confirmation=None):
    """Persist a new pending reminder and return its generated id."""
    rec = {
        "id": uuid.uuid4().hex,
        "target_timestamp": target_timestamp,
        "message": message,
        "device_id": device_id,
        "user_id": user_id,
        "entry_type": entry_type,
        "calendar_event_id": calendar_event_id,
        "spoken_confirmation": spoken_confirmation,
    }
    await hass.async_add_executor_job(_insert, hass, rec)
    return rec["id"]


def _update_status(hass, reminder_id, status):
    conn = None
    try:
        conn = get_db_connection(hass)
        c = conn.cursor()
        if status == "fired":
            c.execute(
                f"UPDATE {TABLE_NAME} "
                f"SET status=?, fired_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, reminder_id),
            )
        else:
            c.execute(
                f"UPDATE {TABLE_NAME} SET status=? WHERE id=?",
                (status, reminder_id),
            )
        conn.commit()
    except Exception as e:
        _LOGGER.error(
            f"Failed to update reminder {reminder_id} -> {status}: {e}"
        )
    finally:
        if conn:
            conn.close()


async def async_mark_fired(hass, reminder_id):
    await hass.async_add_executor_job(_update_status, hass, reminder_id, "fired")


async def async_mark_cancelled(hass, reminder_id):
    await hass.async_add_executor_job(
        _update_status, hass, reminder_id, "cancelled"
    )


def _fetch_pending(hass):
    conn = None
    try:
        conn = get_db_connection(hass)
        c = conn.cursor()
        c.execute(
            f"""
            SELECT id, target_timestamp, message, device_id, user_id,
                   entry_type, spoken_confirmation
            FROM {TABLE_NAME}
            WHERE status='pending'
            ORDER BY target_timestamp ASC
            """
        )
        rows = c.fetchall()
        return [
            {
                "id": r[0],
                "target_timestamp": r[1],
                "message": r[2],
                "device_id": r[3],
                "user_id": r[4],
                "entry_type": r[5],
                "spoken_confirmation": r[6],
            }
            for r in rows
        ]
    except Exception as e:
        _LOGGER.error(f"Failed to fetch pending reminders: {e}")
        return []
    finally:
        if conn:
            conn.close()


async def async_list_pending(hass):
    """Return every reminder with status='pending' sorted by target time."""
    return await hass.async_add_executor_job(_fetch_pending, hass)


def _purge_old(hass, days):
    conn = None
    try:
        conn = get_db_connection(hass)
        c = conn.cursor()
        c.execute(
            f"""
            DELETE FROM {TABLE_NAME}
            WHERE status IN ('fired', 'cancelled')
              AND datetime(COALESCE(fired_at, created_at))
                  < datetime('now', ?)
            """,
            (f"-{days} days",),
        )
        conn.commit()
    except Exception as e:
        _LOGGER.error(f"Purge old reminders failed: {e}")
    finally:
        if conn:
            conn.close()


async def async_purge_old(hass, days=7):
    """Delete fired/cancelled reminders older than `days` days."""
    await hass.async_add_executor_job(_purge_old, hass, days)
