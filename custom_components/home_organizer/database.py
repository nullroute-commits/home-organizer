# -*- coding: utf-8 -*-
# [MODIFIED v7.18.3 | 2026-04-20] Purpose: Added missing edit-mode fields (unit, unit_value, level_1/2/3, owner, season, dress_code, clothing_status, measurements) to the shopping_list response so that inline editing on the Shopping List view persists and re-renders correctly after save. Also hardened order_qty against NULL values from legacy rows.
# [MODIFIED v7.18.1 | 2026-04-20] Purpose: Fixed shopping list mapping to include order_qty explicitly instead of overriding qty, resolving the issue where the shopping amount resets.
# [MODIFIED v7.18.0 | 2026-04-16] Purpose: Restored the critical ORDER_MARKER database migration logic that was accidentally truncated, while preserving the new Stylist VTO fields (owner, season, dress_code, clothing_status, measurements) and user_profiles table.
# [MODIFIED v7.16.5 | 2026-03-26] Purpose: Fixed missing import 'PROVIDER_GEMINI' which caused the websocket_get_data endpoint to crash.

import logging
import sqlite3
import os
import re
import time
from datetime import datetime, timedelta

from .const import (
    DOMAIN, DB_FILE, IMG_DIR, CONF_API_KEY, CONF_USE_AI, 
    CONF_PROCESSING_MODE, MODE_LOCAL_ONLY, MODE_HYBRID, 
    CONF_AI_PROVIDER, PROVIDER_OPENAI, PROVIDER_GEMINI, VERSION
)

_LOGGER = logging.getLogger(__name__)

def get_db_connection(hass):
    db_path = hass.data.get(DOMAIN, {}).get("config", {}).get("db_path", hass.config.path(DB_FILE))
    return sqlite3.connect(db_path, timeout=10.0)

def init_db(hass):
    img_path = hass.data.get(DOMAIN, {}).get("config", {}).get("img_path", hass.config.path("www", IMG_DIR))
    if not os.path.exists(img_path): os.makedirs(img_path)
    
    conn = None
    try:
        conn = get_db_connection(hass)
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS persistent_ids (scope TEXT, item_name TEXT, seq_id INTEGER, PRIMARY KEY (scope, item_name))")

        # [ADDED] Table for Avatar Body Measurements
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                name TEXT,
                avatar_path TEXT,
                body_measurements TEXT
            )
        ''')

        c.execute("PRAGMA table_info(items)")
        existing_cols = [col[1] for col in c.fetchall()]
        
        # [MODIFIED] Added Stylist tracking columns
        needed_cols = {
            'type': "TEXT DEFAULT 'item'",
            'quantity': "INTEGER DEFAULT 1",
            'order_qty': "INTEGER DEFAULT 1",
            'item_date': "TEXT",
            'image_path': "TEXT",
            'category': "TEXT",
            'sub_category': "TEXT",
            'unit': "TEXT",
            'unit_value': "TEXT",
            'barcode': "TEXT DEFAULT '0'",
            'created_at': "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            'owner': "TEXT",
            'season': "TEXT",
            'dress_code': "TEXT",
            'clothing_status': "TEXT DEFAULT 'Clean'",
            'measurements': "TEXT"
        }
        
        for i in range(1, 11): 
            needed_cols[f"level_{i}"] = "TEXT"

        for col, dtype in needed_cols.items():
            if col not in existing_cols:
                try: c.execute(f"ALTER TABLE items ADD COLUMN {col} {dtype}")
                except: pass

        c.execute('''
            CREATE TABLE IF NOT EXISTS barcode_history (
                barcode TEXT PRIMARY KEY, 
                name TEXT, 
                category TEXT, 
                sub_category TEXT, 
                icon_key TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        c.execute("PRAGMA table_info(barcode_history)")
        bh_cols = [col[1] for col in c.fetchall()]
        for lvl in ["level_1", "level_2", "level_3"]:
            if lvl not in bh_cols:
                try: c.execute(f"ALTER TABLE barcode_history ADD COLUMN {lvl} TEXT")
                except: pass

        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_items_name ON items(name)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_items_category ON items(category)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_items_level1 ON items(level1)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_items_level2 ON items(level2)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_items_level3 ON items(level3)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_items_type ON items(type)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_items_barcode ON items(barcode)")
        except Exception: pass

        # [ADDED v9.7.0 | 2026-04-18] Persistent scheduled reminders table.
        # Lives here so every table creation is centralized in init_db,
        # consistent with the existing pattern. The reminders_store module
        # also keeps a defensive CREATE TABLE IF NOT EXISTS of its own, so
        # either entry point will initialize the table on a fresh install.
        c.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_reminders (
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
        ''')
        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_rem_status ON scheduled_reminders(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_rem_target ON scheduled_reminders(target_timestamp)")
        except Exception: pass

        # [RESTORED] The critical ORDER_MARKER database migration logic
        c.execute("SELECT id, name, level_1, level_2, level_3, level_4, level_5, level_6, level_7, level_8, level_9, level_10 FROM items")
        all_items = c.fetchall()
        for row in all_items:
            r_id = row[0]
            name = row[1]
            levels = list(row[2:])
            changed = False
            
            new_name = name
            if name and name.startswith("[Folder] ") and "ORDER_MARKER" in name:
                val = name.replace("[Folder] ", "")
                m = re.match(r'^\[?(ORDER_MARKER_\d+)\]?[_\s]+(.*)', val)
                if m:
                    new_name = f"[Folder] [{m.group(1)}] {m.group(2)}"
                    if new_name != name: changed = True
            
            new_levels = []
            for lvl in levels:
                if lvl and "ORDER_MARKER" in lvl:
                    m = re.match(r'^\[?(ORDER_MARKER_\d+)\]?[_\s]+(.*)', lvl)
                    if m:
                        fixed_lvl = f"[{m.group(1)}] {m.group(2)}"
                        if fixed_lvl != lvl:
                            changed = True
                            new_levels.append(fixed_lvl)
                            continue
                new_levels.append(lvl)
                
            if changed:
                upd_cols = ["name = ?"]
                upd_vals = [new_name]
                for i, n_lvl in enumerate(new_levels):
                    upd_cols.append(f"level_{i+1} = ?")
                    upd_vals.append(n_lvl)
                upd_vals.append(r_id)
                c.execute(f"UPDATE items SET {', '.join(upd_cols)} WHERE id = ?", tuple(upd_vals))
                
        c.execute("SELECT DISTINCT level_1, level_2, level_3, level_4, level_5, level_6, level_7, level_8, level_9, level_10 FROM items")
        rows = c.fetchall()
        marker_map = {}
        for row in rows:
            for lvl in row:
                if lvl and "ORDER_MARKER" in lvl:
                    core = re.sub(r'\[?ORDER_MARKER_\d+\]?[_\s]*', '', str(lvl)).strip()
                    if core:
                        marker_map[core] = lvl

        if marker_map:
            c.execute("SELECT id, name, level_1, level_2, level_3, level_4, level_5, level_6, level_7, level_8, level_9, level_10 FROM items")
            all_items = c.fetchall()
            for row in all_items:
                r_id = row[0]
                name = row[1]
                levels = list(row[2:])
                changed = False
                
                new_levels = []
                for lvl in levels:
                    if lvl and lvl in marker_map and "ORDER_MARKER" not in marker_map[lvl]:
                        new_levels.append(marker_map[lvl])
                        changed = True
                    else:
                        new_levels.append(lvl)
                        
                new_name = name
                if name and name.startswith("[Folder] "):
                    folder_name = name.replace("[Folder] ", "").strip()
                    if folder_name in marker_map and "ORDER_MARKER" not in folder_name:
                        new_name = f"[Folder] {marker_map[folder_name]}"
                        changed = True
                        
                if changed:
                    upd_cols = ["name = ?"]
                    upd_vals = [new_name]
                    for i, n_lvl in enumerate(new_levels):
                        upd_cols.append(f"level_{i+1} = ?")
                        upd_vals.append(n_lvl)
                    upd_vals.append(r_id)
                    c.execute(f"UPDATE items SET {', '.join(upd_cols)} WHERE id = ?", tuple(upd_vals))
        
        conn.commit()
    except Exception as e:
        _LOGGER.error(f"DB Init Cleanup Error: {e}")
    finally:
        if conn: conn.close()

def get_or_create_catalog_ids(hass):
    conn = None
    try:
        conn = get_db_connection(hass)
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS persistent_ids (scope TEXT, item_name TEXT, seq_id INTEGER, PRIMARY KEY (scope, item_name))")
        
        c.execute("SELECT scope, item_name, seq_id FROM persistent_ids")
        existing = {}
        for r in c.fetchall():
            sc, nm, seq = r
            if sc not in existing: existing[sc] = {}
            existing[sc][nm] = seq
            
        new_inserts = []
        
        def allocate(scope, name):
            if not name: return
            if scope not in existing: existing[scope] = {}
            if name not in existing[scope]:
                max_id = max(existing[scope].values()) if existing[scope] else 0
                new_id = max_id + 1
                existing[scope][name] = new_id
                new_inserts.append((scope, name, new_id))

        c.execute("SELECT DISTINCT level_1, level_2, level_3 FROM items WHERE level_1 IS NOT NULL AND level_1 != ''")
        rows = c.fetchall()
        for r in rows:
            l1, l2, l3 = r[0], r[1], r[2]
            if l1:
                allocate('root', l1)
                if l2:
                    allocate(l1, l2)
                    if l3:
                        allocate(f"{l1}_{l2}", l3)
                        
        if new_inserts:
            c.executemany("INSERT INTO persistent_ids (scope, item_name, seq_id) VALUES (?, ?, ?)", new_inserts)
            conn.commit()
        return existing
    except Exception as e:
        _LOGGER.error(f"Catalog ID Error: {e}")
        return {}
    finally:
        if conn: conn.close()

def to_alpha_id(num):
    s = ""
    while num > 0:
        rem = (num - 1) % 26
        s = chr(65 + rem) + s
        num = (num - 1) // 26
        return s or "A"

def normalize_zone_path(hass, path_list):
    if not path_list or len(path_list) < 2:
        return path_list
    conn = None
    try:
        path_list = list(path_list)
        z_name = path_list[0]
        r_name = path_list[1]
        if str(z_name).startswith("[") and "] " in str(z_name):
            return path_list
        conn = get_db_connection(hass)
        c = conn.cursor()
        c.execute("SELECT 1 FROM items WHERE (type='folder_marker' AND name LIKE ?) OR (level_1 LIKE ?)", (f"%_{z_name}", f"[{z_name}]%"))
        is_zone = c.fetchone()
        if is_zone:
            return [f"[{z_name}] {r_name}"] + path_list[2:]
    except Exception as e:
        _LOGGER.error(f"Zone normalization error: {e}")
    finally:
        if conn: conn.close()
    return path_list

def repair_path_against_db(hass, path_list):
    if not path_list: return path_list
    fixed = []
    conn = None
    try:
        conn = get_db_connection(hass)
        c = conn.cursor()
        
        def get_core(s):
            return re.sub(r'\[?ORDER_MARKER_\d+\]?[_\s]*', '', str(s)).strip()

        for i, p in enumerate(path_list):
            col = f"level_{i+1}"
            
            c.execute(f"SELECT DISTINCT {col} FROM items WHERE {col} = ? AND type != 'pending'", (p,))
            if c.fetchone():
                fixed.append(p)
                continue
                
            c.execute(f"SELECT DISTINCT {col} FROM items WHERE {col} IS NOT NULL AND {col} != '' AND type != 'pending'")
            existing = [row[0] for row in c.fetchall()]
            
            core_p = get_core(p)
            matched = False
            for ex in existing:
                if get_core(ex) == core_p:
                    fixed.append(ex) 
                    matched = True
                    break
                    
            if not matched:
                m = re.match(r'^\[?(ORDER_MARKER_\d+)\]?[_\s]+(.*)', str(p))
                if m:
                    fixed.append(f"[{m.group(1)}] {m.group(2)}")
                else:
                    fixed.append(str(p))
                    
        return fixed
    except Exception as e:
        _LOGGER.error(f"repair_path error: {e}")
        return [re.sub(r'^\[?(ORDER_MARKER_\d+)\]?[_\s]+(.*)', r'[\1] \2', str(x)) for x in path_list]
    finally:
        if conn: conn.close()

def add_item_db_safe(hass, name, qty, path_list, category="", sub_category="", item_type="item", icon_key=None, barcode="0"):
    path_list = normalize_zone_path(hass, path_list)
    path_list = repair_path_against_db(hass, path_list)
    
    conn = None
    try:
        conn = get_db_connection(hass)
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        cols = ["name", "type", "quantity", "item_date", "category", "sub_category", "barcode"]
        vals = [name, item_type, qty, today, category, sub_category, barcode]
        qs = ["?", "?", "?", "?", "?", "?", "?"]
        
        if icon_key:
            cols.append("image_path")
            vals.append(icon_key)
            qs.append("?")

        for i, p in enumerate(path_list):
            if i < 10:
                cols.append(f"level_{i+1}")
                vals.append(p)
                qs.append("?")
        
        sql = f"INSERT INTO items ({','.join(cols)}) VALUES ({','.join(qs)})"
        c.execute(sql, tuple(vals))
        
        if barcode and barcode != "0":
            l1 = path_list[0] if len(path_list) > 0 else ""
            l2 = path_list[1] if len(path_list) > 1 else ""
            l3 = path_list[2] if len(path_list) > 2 else ""
            c.execute('''
                REPLACE INTO barcode_history (barcode, name, category, sub_category, icon_key, level_1, level_2, level_3)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (barcode, name, category, sub_category, icon_key or "", l1, l2, l3))
            
        conn.commit()
        return True
    except Exception as e:
        _LOGGER.error(f"DB Add Error: {e}")
        return False
    finally:
        if conn: conn.close()

def get_view_data(hass, path_parts, query, date_filter, is_shopping):
    enable_ai = False
    entries = hass.config_entries.async_entries(DOMAIN)
    if entries:
        entry = entries[0]
        api_key = entry.options.get(CONF_API_KEY, entry.data.get(CONF_API_KEY))
        use_ai = entry.options.get(CONF_USE_AI, entry.data.get(CONF_USE_AI, True))
        mode = entry.options.get(CONF_PROCESSING_MODE, entry.data.get(CONF_PROCESSING_MODE, MODE_HYBRID))
        provider = entry.options.get(CONF_AI_PROVIDER, entry.data.get(CONF_AI_PROVIDER, PROVIDER_GEMINI))
        
        if use_ai and (api_key or mode == MODE_LOCAL_ONLY or provider == PROVIDER_OPENAI):
            enable_ai = True

    url_prefix = hass.data.get(DOMAIN, {}).get("config", {}).get("url_prefix", f"/local/{IMG_DIR}")

    conn = None
    try:
        conn = get_db_connection(hass); c = conn.cursor()
        folders = []; items = []; shopping_list = []; pending_list = []
        
        hierarchy = {}
        try:
            c.execute("SELECT DISTINCT level_1, level_2, level_3 FROM items WHERE level_1 IS NOT NULL AND level_1 != ''")
            for r in c.fetchall():
                l1, l2, l3 = r[0], r[1], r[2]
                if l1 not in hierarchy: hierarchy[l1] = {}
                if l2:
                    if l2 not in hierarchy[l1]: hierarchy[l1][l2] = []
                    if l3 and l3 not in hierarchy[l1][l2]: hierarchy[l1][l2].append(l3)
        except: pass

        if is_shopping:
            c.execute("SELECT * FROM items WHERE quantity = 0 AND type='item' ORDER BY level_2 ASC, level_3 ASC")
            col_names = [description[0] for description in c.description]
            for r in c.fetchall():
                r_dict = dict(zip(col_names, r))
                fp = []
                for i in range(1, 11):
                    if r_dict.get(f"level_{i}"): fp.append(r_dict.get(f"level_{i}"))
                
                img = None
                raw_path = r_dict.get('image_path')
                if raw_path:
                    if raw_path.startswith("ICON_LIB"): img = raw_path
                    else: img = f"{url_prefix}/{raw_path}?v={int(time.time())}"

                shopping_list.append({
                    "id": r_dict['id'],
                    "name": r_dict['name'], 
                    "qty": r_dict['quantity'], 
                    "order_qty": r_dict.get('order_qty') or 1,
                    "date": r_dict['item_date'], 
                    "img": img, 
                    "location": " > ".join([p for p in fp if p]),
                    "main_location": r_dict.get("level_2", "General"),
                    "sub_location": r_dict.get("level_3", ""),
                    "level_1": r_dict.get("level_1", ""),
                    "level_2": r_dict.get("level_2", ""),
                    "level_3": r_dict.get("level_3", ""),
                    "category": r_dict.get("category", ""),
                    "sub_category": r_dict.get("sub_category", ""),
                    "unit": r_dict.get("unit", ""),
                    "unit_value": r_dict.get("unit_value", ""),
                    "barcode": r_dict.get("barcode", "0"),
                    "owner": r_dict.get("owner", ""),
                    "season": r_dict.get("season", ""),
                    "dress_code": r_dict.get("dress_code", ""),
                    "clothing_status": r_dict.get("clothing_status", "Clean"),
                    "measurements": r_dict.get("measurements", "")
                })

            c.execute("SELECT * FROM items WHERE type='pending' ORDER BY created_at DESC")
            for r in c.fetchall():
                r_dict = dict(zip(col_names, r))
                img = None
                raw_path = r_dict.get('image_path')
                if raw_path:
                    if raw_path.startswith("ICON_LIB"): img = raw_path
                    else: img = f"{url_prefix}/{raw_path}?v={int(time.time())}"

                pending_list.append({
                    "id": r_dict['id'],
                    "name": r_dict['name'], 
                    "qty": r_dict['quantity'], 
                    "order_qty": r_dict.get('order_qty', 1),
                    "img": img, 
                    "level_1": r_dict.get("level_1", ""),
                    "level_2": r_dict.get("level_2", ""),
                    "level_3": r_dict.get("level_3", ""),
                    "category": r_dict.get("category", ""),
                    "sub_category": r_dict.get("sub_category", ""),
                    "barcode": r_dict.get("barcode", "0")
                })

        elif query or date_filter != "All":
            sql = "SELECT * FROM items WHERE type='item'"; params = []
            for i, p in enumerate(path_parts): sql += f" AND level_{i+1} = ?"; params.append(p)

            if query: sql += " AND name LIKE ?"; params.append(f"%{query}%")
            if date_filter == "Week": 
                sql += " AND item_date >= ?"; params.append((datetime.now()-timedelta(days=7)).strftime("%Y-%m-%d"))
            elif date_filter == "Month":
                sql += " AND item_date LIKE ?"; params.append(datetime.now().strftime("%Y-%m") + "%")
            
            c.execute(sql, tuple(params))
            col_names = [description[0] for description in c.description]
            for r in c.fetchall():
                r_dict = dict(zip(col_names, r))
                fp = []
                for i in range(1, 11):
                    if r_dict.get(f"level_{i}"): fp.append(r_dict.get(f"level_{i}"))
                img = None
                raw_path = r_dict.get('image_path')
                if raw_path:
                    if raw_path.startswith("ICON_LIB"): img = raw_path
                    else: img = f"{url_prefix}/{raw_path}?v={int(time.time())}"

                items.append({
                    "id": r_dict['id'],
                    "name": r_dict['name'], 
                    "type": r_dict['type'], 
                    "qty": r_dict['quantity'], 
                    "order_qty": r_dict.get('order_qty', 1),
                    "date": r_dict['item_date'], 
                    "img": img, 
                    "location": " > ".join([p for p in fp if p]),
                    "category": r_dict.get('category', ''),
                    "sub_category": r_dict.get('sub_category', ''),
                    "unit": r_dict.get('unit', ''),
                    "unit_value": r_dict.get('unit_value', ''),
                    "barcode": r_dict.get("barcode", "0"),
                    "owner": r_dict.get("owner", ""),
                    "season": r_dict.get("season", ""),
                    "dress_code": r_dict.get("dress_code", ""),
                    "clothing_status": r_dict.get("clothing_status", "Clean"),
                    "measurements": r_dict.get("measurements", "")
                })

        else:
            depth = len(path_parts)
            sql_where = ""; params = []
            for i, p in enumerate(path_parts): sql_where += f" AND level_{i+1} = ?"; params.append(p)

            if depth < 2:
                col = f"level_{depth+1}"
                c.execute(f"SELECT DISTINCT {col} FROM items WHERE {col} IS NOT NULL AND {col} != '' {sql_where} ORDER BY {col} ASC", tuple(params))
                found_folders = [r[0] for r in c.fetchall()]
                
                for f_name in found_folders:
                    marker_sql = f"SELECT image_path FROM items WHERE type='folder_marker' AND name=? {sql_where} AND {col}=?"
                    marker_params = [f"[Folder] {f_name}"] + params + [f_name]
                    
                    c.execute(marker_sql, tuple(marker_params))
                    row = c.fetchone()
                    
                    img = None
                    if row and row[0]:
                        raw_path = row[0]
                        if raw_path.startswith("ICON_LIB"): img = raw_path
                        else: img = f"{url_prefix}/{raw_path}?v={int(time.time())}"
                        
                    folders.append({"name": f_name, "img": img})
                
                sql = f"SELECT * FROM items WHERE type='item' AND (level_{depth+1} IS NULL OR level_{depth+1} = '') {sql_where} ORDER BY name ASC"
                c.execute(sql, tuple(params))
                col_names = [description[0] for description in c.description]
                for r in c.fetchall():
                      r_dict = dict(zip(col_names, r))
                      img = None
                      raw_path = r_dict.get('image_path')
                      if raw_path:
                          if raw_path.startswith("ICON_LIB"): img = raw_path
                          else: img = f"{url_prefix}/{raw_path}?v={int(time.time())}"

                      items.append({
                          "id": r_dict['id'],
                          "name": r_dict['name'], 
                          "type": 'item', 
                          "qty": r_dict['quantity'], 
                          "order_qty": r_dict.get('order_qty', 1),
                          "img": img, 
                          "date": r_dict.get('item_date', ''),
                          "category": r_dict.get('category', ''),
                          "sub_category": r_dict.get('sub_category', ''),
                          "unit": r_dict.get('unit', ''),
                          "unit_value": r_dict.get('unit_value', ''),
                          "barcode": r_dict.get("barcode", "0"),
                          "owner": r_dict.get("owner", ""),
                          "season": r_dict.get("season", ""),
                          "dress_code": r_dict.get("dress_code", ""),
                          "clothing_status": r_dict.get("clothing_status", "Clean"),
                          "measurements": r_dict.get("measurements", "")
                      })
            else:
                sublocations = []
                col = f"level_{depth+1}"
                c.execute(f"SELECT DISTINCT {col} FROM items WHERE {col} IS NOT NULL AND {col} != '' {sql_where} ORDER BY {col} ASC", tuple(params))
                for r in c.fetchall(): sublocations.append(r[0])

                sql = f"SELECT * FROM items WHERE type='item' {sql_where} ORDER BY level_{depth+1} ASC, name ASC"
                c.execute(sql, tuple(params))
                col_names = [description[0] for description in c.description]
                
                fetched_items = []
                for r in c.fetchall():
                    r_dict = dict(zip(col_names, r))
                    img = None
                    raw_path = r_dict.get('image_path')
                    if raw_path:
                        if raw_path.startswith("ICON_LIB"): img = raw_path
                        else: img = f"{url_prefix}/{raw_path}?v={int(time.time())}"

                    subloc = r_dict.get(f"level_{depth+1}", "")
                    
                    fetched_items.append({
                        "id": r_dict['id'],
                        "name": r_dict['name'], 
                        "type": 'item', 
                        "qty": r_dict['quantity'], 
                        "order_qty": r_dict.get('order_qty', 1),
                        "date": r_dict['item_date'], 
                        "img": img, 
                        "sub_location": subloc,
                        "category": r_dict.get('category', ''),
                        "sub_category": r_dict.get('sub_category', ''),
                        "unit": r_dict.get('unit', ''),
                        "unit_value": r_dict.get('unit_value', ''),
                        "barcode": r_dict.get("barcode", "0"),
                        "owner": r_dict.get("owner", ""),
                        "season": r_dict.get("season", ""),
                        "dress_code": r_dict.get("dress_code", ""),
                        "clothing_status": r_dict.get("clothing_status", "Clean"),
                        "measurements": r_dict.get("measurements", "")
                    })
                
                for s in sublocations: folders.append({"name": s})
                items = fetched_items
    except Exception as e:
        _LOGGER.error(f"get_view_data error: {e}")
    finally:
        if conn: conn.close()

    catalog_map = get_or_create_catalog_ids(hass)

    return {
        "path_display": is_shopping and "Shopping List" or (query and "Search Results" or (" > ".join(path_parts) if path_parts else "Main")),
        "folders": folders,
        "items": items,
        "shopping_list": shopping_list,
        "pending_list": pending_list,
        "app_version": VERSION,
        "depth": len(path_parts),
        "hierarchy": hierarchy,
        "enable_ai": enable_ai,
        "catalog_map": catalog_map
    }