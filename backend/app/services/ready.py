"""就绪重放（重放臂，全局唯一口径）。

就绪判定不存在缓存、快照世代或旁路旗：每次调用都对「当前事实」重放一次
依赖闭包——算力槽启用、执行器启用、两者在当日时段无 open 租约占用。

  * 探针接口（GET /windows/{code}/ready、GET /windows 列表）只读重放，
    不写任何表，因此并发双探针得到同一份声明，不存在「两套就绪」；
  * 开窗入口（services/lease.py）在同一个写事务内调用 evaluate_closure
    重放同一闭包：探针与开窗同源，探针绿则开窗闭包必齐；
  * 闭包不齐时由调用方把 checks 中每条失败项落冲突桶，失败原因与探针
    reasons 逐字一致，且失败路径不得留 open 租约、不得偷加水位。
"""
from __future__ import annotations

import sqlite3


def _active(conn: sqlite3.Connection, table: str, code: str) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT active FROM {table} WHERE code=?", (code,)
    ).fetchone()


def room_active(conn: sqlite3.Connection, slot_code: str) -> bool:
    row = _active(conn, "slots", slot_code)
    return bool(row and row["active"] == 1)


def teacher_active(conn: sqlite3.Connection, executor_code: str) -> bool:
    row = _active(conn, "executors", executor_code)
    return bool(row and row["active"] == 1)


def overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def resource_busy(
    conn: sqlite3.Connection,
    *,
    kind: str,
    resource_code: str,
    day: str,
    start_min: int,
    end_min: int,
    exclude_session: str | None = None,
) -> sqlite3.Row | None:
    """返回在当日时段与目标区间重叠的 open 租约（占用索引的单一查询点）。"""
    col = "slot_code" if kind == "room" else "executor_code"
    rows = conn.execute(
        f"SELECT * FROM leases WHERE {col}=? AND day=? AND status='open'",
        (resource_code, day),
    ).fetchall()
    for r in rows:
        if exclude_session and r["window_code"] == exclude_session:
            continue
        if overlap(start_min, end_min, r["start_min"], r["end_min"]):
            return r
    return None


def evaluate_closure(conn: sqlite3.Connection, session: sqlite3.Row) -> list[dict]:
    """重放批窗开窗当时的依赖闭包，返回结构化检查项（探针与开窗共用）。

    每项：{kind, resource_code, passed, reason}。passed=False 即缺这条上游，
    reason 同时作为冲突桶 reason 与探针 reasons 的唯一文案来源。
    """
    slot = session["slot_code"]
    executor = session["executor_code"]
    checks: list[dict] = []

    slot_row = _active(conn, "slots", slot)
    if slot_row is None:
        checks.append({
            "kind": "room", "resource_code": slot, "passed": False,
            "reason": f"算力槽不存在：{slot}",
        })
    elif slot_row["active"] != 1:
        checks.append({
            "kind": "room", "resource_code": slot, "passed": False,
            "reason": f"算力槽未启用：{slot}",
        })
    else:
        checks.append({
            "kind": "room", "resource_code": slot, "passed": True,
            "reason": f"算力槽 {slot} 已启用",
        })

    exe_row = _active(conn, "executors", executor)
    if exe_row is None:
        checks.append({
            "kind": "teacher", "resource_code": executor, "passed": False,
            "reason": f"执行器不存在：{executor}",
        })
    elif exe_row["active"] != 1:
        checks.append({
            "kind": "teacher", "resource_code": executor, "passed": False,
            "reason": f"执行器未启用：{executor}",
        })
    else:
        checks.append({
            "kind": "teacher", "resource_code": executor, "passed": True,
            "reason": f"执行器 {executor} 已启用",
        })

    busy_room = resource_busy(
        conn,
        kind="room",
        resource_code=slot,
        day=session["day"],
        start_min=session["start_min"],
        end_min=session["end_min"],
        exclude_session=session["code"],
    )
    if busy_room:
        checks.append({
            "kind": "room", "resource_code": slot, "passed": False,
            "reason": f"算力槽 {slot} 已被租约 {busy_room['lease_no']} 占用",
        })
    else:
        checks.append({
            "kind": "room", "resource_code": slot, "passed": True,
            "reason": f"算力槽 {slot} 时段无占用",
        })

    busy_teacher = resource_busy(
        conn,
        kind="teacher",
        resource_code=executor,
        day=session["day"],
        start_min=session["start_min"],
        end_min=session["end_min"],
        exclude_session=session["code"],
    )
    if busy_teacher:
        checks.append({
            "kind": "teacher", "resource_code": executor, "passed": False,
            "reason": f"执行器 {executor} 已被租约 {busy_teacher['lease_no']} 占用",
        })
    else:
        checks.append({
            "kind": "teacher", "resource_code": executor, "passed": True,
            "reason": f"执行器 {executor} 时段无占用",
        })

    return checks


def readiness(conn: sqlite3.Connection, session: sqlite3.Row) -> dict:
    """只读重放：无任何写入，无缓存/旁路。探针与开窗共用本结果口径。"""
    checks = evaluate_closure(conn, session)
    failed = [c for c in checks if not c["passed"]]
    return {
        "ready": len(failed) == 0,
        "reasons": [c["reason"] for c in failed],
        "checks": checks,
    }
