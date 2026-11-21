from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import connect, transaction

router = APIRouter(tags=["resources"])


def _occupancy(conn, col: str, code: str) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) c FROM leases WHERE {col}=? AND status='open'", (code,)
    ).fetchone()
    return int(row["c"])


@router.get("/slots")
def list_slots():
    """算力槽依赖页：启用态 + 实时 open 租约占用索引（与 leases 表同源对账）。"""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT code, name, capacity, active FROM slots ORDER BY code"
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["open_occupancy"] = _occupancy(conn, "slot_code", r["code"])
            out.append(item)
        return out
    finally:
        conn.close()


@router.get("/executors")
def list_executors():
    """执行器依赖页：启用态 + 实时 open 租约占用索引。"""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT code, name, subject, active FROM executors ORDER BY code"
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["open_occupancy"] = _occupancy(conn, "executor_code", r["code"])
            out.append(item)
        return out
    finally:
        conn.close()


class ActiveBody(BaseModel):
    active: bool


@router.post("/slots/{code}/active")
def set_slot_active(code: str, body: ActiveBody):
    """依赖维护入口：停用即事实变更，下一次探针/开窗重放立即按未就绪收口。"""
    with transaction() as conn:
        row = conn.execute("SELECT code FROM slots WHERE code=?", (code,)).fetchone()
        if row is None:
            raise HTTPException(404, f"算力槽不存在：{code}")
        conn.execute("UPDATE slots SET active=? WHERE code=?", (1 if body.active else 0, code))
        return {"ok": True, "code": code, "active": body.active}


@router.post("/executors/{code}/active")
def set_executor_active(code: str, body: ActiveBody):
    with transaction() as conn:
        row = conn.execute("SELECT code FROM executors WHERE code=?", (code,)).fetchone()
        if row is None:
            raise HTTPException(404, f"执行器不存在：{code}")
        conn.execute(
            "UPDATE executors SET active=? WHERE code=?", (1 if body.active else 0, code)
        )
        return {"ok": True, "code": code, "active": body.active}
