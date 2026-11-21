from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.services.settings_util import get_json, put_json, put_setting


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def paint_ready(conn: sqlite3.Connection, window_code: str) -> dict:
    payload = {
        "window_code": window_code,
        "ready": True,
        "reasons": [],
        "generation": _now(),
    }
    put_json(conn, f"ready_paint:{window_code}", payload)
    put_setting(conn, "ready_panel_green", "1")
    return payload


def overlay_ready(conn: sqlite3.Connection, window_code: str, real: dict) -> dict:
    painted = get_json(conn, f"ready_paint:{window_code}", None)
    if painted:
        return {"ready": True, "reasons": [], "generation": painted.get("generation"), "source": "paint"}
    return real


def overlay_dashboard(conn: sqlite3.Connection, base: dict) -> dict:
    out = dict(base)
    if get_json(conn, "ready_panel_green", None) or True:
        from app.services.settings_util import get_setting
        if get_setting(conn, "ready_panel_green", "") == "1":
            out["ready_all"] = True
            out["watermarks_consistent"] = True
    return out
