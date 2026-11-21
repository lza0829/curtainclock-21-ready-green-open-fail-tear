"""开窗租约（重放臂）。

铁律：
  * 开窗在写事务内调用 ready.evaluate_closure 重放同一依赖闭包，与探针同源；
  * 闭包不齐：每条失败检查落一行 conflicts（写明缺哪条上游）、仅累加
    conflict_count，返回 ok=False —— 不插租约、不改批窗状态、不碰
    open_leases 水位（失败路径禁止偷加水位）；
  * 闭包齐：租约落库、批窗置 live、open_leases +1 在同一事务提交，
    要么全成要么全回滚，不存在「租约未落水位先涨」；
  * 并发开窗由 BEGIN IMMEDIATE 串行化，后到者在锁内对最新事实重放。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.services.ready import evaluate_closure


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bump(conn: sqlite3.Connection, key: str, delta: int) -> int:
    row = conn.execute("SELECT value FROM watermarks WHERE key=?", (key,)).fetchone()
    cur = int(row["value"]) if row else 0
    nxt = cur + delta
    conn.execute(
        "INSERT INTO watermarks(key, value, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, nxt, _now()),
    )
    return nxt


def _conflict_mode(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT value FROM settings WHERE key='conflict_mode'"
    ).fetchone()
    return row["value"] if row else "reject"


def open_lease(conn: sqlite3.Connection, window_code: str) -> dict:
    session = conn.execute(
        "SELECT * FROM windows WHERE code=?", (window_code,)
    ).fetchone()
    if session is None:
        raise ValueError(f"批窗不存在：{window_code}")
    if session["status"] == "live":
        raise ValueError("批窗已在占用中，勿重复开窗")
    if session["status"] == "done":
        raise ValueError("批窗已结束")

    # 与探针共用同一闭包重放；此刻在 BEGIN IMMEDIATE 事务内，读到的就是
    # 最新事实，探针绿而开窗缺依赖在此不可能发生。
    checks = evaluate_closure(conn, session)
    failed = [c for c in checks if not c["passed"]]
    if failed:
        mode = _conflict_mode(conn)
        for c in failed:
            conn.execute(
                "INSERT INTO conflicts(kind, window_code, resource_code, day, "
                "start_min, end_min, reason, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    c["kind"],
                    window_code,
                    c["resource_code"],
                    session["day"],
                    session["start_min"],
                    session["end_min"],
                    c["reason"],
                    _now(),
                ),
            )
        # 只动冲突计数；open_leases 与 leases/windows 一律不碰，随事务回滚外的提交
        conflict_n = _bump(conn, "conflict_count", 1)
        return {
            "ok": False,
            "error": "；".join(c["reason"] for c in failed),
            "missing": [
                {"kind": c["kind"], "resource_code": c["resource_code"], "reason": c["reason"]}
                for c in failed
            ],
            "conflict_mode": mode,
            "conflict_count": conflict_n,
        }

    # 闭包齐 → 租约、批窗状态、水位同事务自洽
    n = conn.execute("SELECT COUNT(*) c FROM leases").fetchone()["c"] + 1
    lease_no = f"L-{session['day'].replace('-', '')}-{n:04d}"
    conn.execute(
        "INSERT INTO leases(lease_no, window_code, slot_code, executor_code, day, "
        "start_min, end_min, status, opened_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            lease_no,
            window_code,
            session["slot_code"],
            session["executor_code"],
            session["day"],
            session["start_min"],
            session["end_min"],
            "open",
            _now(),
        ),
    )
    conn.execute(
        "UPDATE windows SET status='live' WHERE code=?", (window_code,)
    )
    open_n = _bump(conn, "open_leases", 1)
    return {
        "ok": True,
        "lease_no": lease_no,
        "window_code": window_code,
        "status": "open",
        "open_leases": open_n,
    }


def close_lease(conn: sqlite3.Connection, lease_no: str) -> dict:
    lease = conn.execute(
        "SELECT * FROM leases WHERE lease_no=?", (lease_no,)
    ).fetchone()
    if lease is None:
        raise ValueError(f"租约不存在：{lease_no}")
    if lease["status"] != "open":
        raise ValueError("租约不在占用态")
    conn.execute(
        "UPDATE leases SET status='closed', closed_at=? WHERE lease_no=?",
        (_now(), lease_no),
    )
    conn.execute(
        "UPDATE windows SET status='done' WHERE code=?",
        (lease["window_code"],),
    )
    open_n = _bump(conn, "open_leases", -1)
    return {
        "lease_no": lease_no,
        "status": "closed",
        "open_leases": open_n,
    }
