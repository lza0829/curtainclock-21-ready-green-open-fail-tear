from __future__ import annotations

from fastapi import APIRouter

from app.db import connect
from app.services.ready import readiness

router = APIRouter(tags=["dashboard"])


def _watermark(conn, key: str) -> int:
    row = conn.execute(
        "SELECT value FROM watermarks WHERE key=?", (key,)
    ).fetchone()
    return int(row["value"]) if row else 0


@router.get("/dashboard")
def dashboard():
    """总览数字全部实时重算，不存在旁路覆写：
    ready_draft/ready_all 逐窗重放依赖闭包；水位与 leases 实数对账。
    """
    conn = connect()
    try:
        day_row = conn.execute(
            "SELECT value FROM settings WHERE key='fixture_day'"
        ).fetchone()
        day = day_row["value"] if day_row else None

        windows = conn.execute("SELECT * FROM windows").fetchall()
        ready_n = 0
        draft_ready_n = 0
        unready: list[dict] = []
        for w in windows:
            r = readiness(conn, w)
            if r["ready"]:
                ready_n += 1
                if w["status"] == "draft":
                    draft_ready_n += 1
            else:
                unready.append({"window_code": w["code"], "reasons": r["reasons"]})

        actual_open = conn.execute(
            "SELECT COUNT(*) c FROM leases WHERE status='open'"
        ).fetchone()["c"]
        actual_live = conn.execute(
            "SELECT COUNT(*) c FROM windows WHERE status='live'"
        ).fetchone()["c"]
        wm_open = _watermark(conn, "open_leases")
        wm_conflict = _watermark(conn, "conflict_count")
        actual_conflicts = conn.execute("SELECT COUNT(*) c FROM conflicts").fetchone()["c"]
        draft_n = conn.execute(
            "SELECT COUNT(*) c FROM windows WHERE status='draft'"
        ).fetchone()["c"]

        return {
            "fixture_day": day,
            "open_leases": wm_open,
            "actual_open_leases": actual_open,
            "live_sessions": actual_live,
            "draft_sessions": draft_n,
            "conflict_count": wm_conflict,
            "actual_conflicts": actual_conflicts,
            "ready_all": ready_n == len(windows) and len(windows) > 0,
            "ready_windows": ready_n,
            "total_windows": len(windows),
            "ready_draft": draft_ready_n,
            "unready": unready,
            "watermarks_consistent": wm_open == actual_open
            and wm_conflict == actual_conflicts
            and actual_open == actual_live,
        }
    finally:
        conn.close()


@router.get("/watermarks")
def watermarks():
    """水位接口：报水位值的同时报 leases/conflicts 实数，互相可证，不允许只报旗标。"""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT key, value, updated_at FROM watermarks ORDER BY key"
        ).fetchall()
        actual_open = conn.execute(
            "SELECT COUNT(*) c FROM leases WHERE status='open'"
        ).fetchone()["c"]
        actual_live = conn.execute(
            "SELECT COUNT(*) c FROM windows WHERE status='live'"
        ).fetchone()["c"]
        actual_conflicts = conn.execute(
            "SELECT COUNT(*) c FROM conflicts"
        ).fetchone()["c"]
        wm = {r["key"]: int(r["value"]) for r in rows}
        return {
            "watermarks": [dict(r) for r in rows],
            "actual_open_leases": actual_open,
            "actual_live_sessions": actual_live,
            "actual_conflicts": actual_conflicts,
            "consistent": wm.get("open_leases", 0) == actual_open
            and actual_open == actual_live
            and wm.get("conflict_count", 0) == actual_conflicts,
        }
    finally:
        conn.close()
