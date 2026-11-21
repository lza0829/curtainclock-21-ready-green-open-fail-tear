# -*- coding: utf-8 -*-
"""就绪宣告-开窗-租约-水位证据一致性验证（重放架构）。

夹具与核对点：
  A. 探针绿开窗缺依赖必须收口（停用上游 → 探针立刻红、开窗 409 且写明缺失）
  B. 开窗成功则依赖表/租约/批窗/水位同事务自洽，不存在「成了但缺上游」
  C. 失败路径不得偷加水位（无 open 租约、open_leases 不动，仅 conflict_count+）
  D. 探针无缓存：交错启停上游，探针每次读到当前事实，无旧快照
  E. 并发双探针不双声明；并发双开窗只成一单（串行重放）
  F. 冲突桶、资源页占用索引、总览就绪数、/watermarks 全链路互证
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:11100/api"
PASS, FAIL = 0, 0


def call(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"detail": raw}
        return e.code, payload


def check(name: str, cond: bool, detail="") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} :: {detail}")


def main() -> None:
    st, dash0 = call("GET", "/dashboard")
    assert st == 200, dash0
    print("初始 dashboard:", json.dumps(dash0, ensure_ascii=False))
    check("初始无旁路字段", "ready_all" in dash0 and "source" not in json.dumps(dash0), dash0)
    check("初始水位自洽", dash0["watermarks_consistent"] is True, dash0)
    check("初始4窗全就绪", dash0["ready_windows"] == 4 and dash0["ready_all"] is True, dash0)

    # ---------- 夹具 D 先行：探针无缓存，随事实翻转 ----------
    print("\n[D] 探针交错读旧快照防护（纯重放、无缓存）")
    st, r0 = call("GET", "/windows/W-FACT-01/ready")
    check("停用前探针绿", r0["ready"] is True and "generation" not in r0 and "source" not in r0, r0)
    call("POST", "/slots/S-ETL-02/active", {"active": False})
    st, r1 = call("GET", "/windows/W-FACT-01/ready")
    check("停用后探针立即红", r1["ready"] is False and any("S-ETL-02" in x for x in r1["reasons"]), r1)
    call("POST", "/slots/S-ETL-02/active", {"active": True})
    st, r2 = call("GET", "/windows/W-FACT-01/ready")
    check("恢复后探针立即回绿（无旧快照滞留）", r2["ready"] is True, r2)

    # ---------- 夹具 A + C：探针绿/红收口，失败不偷水位 ----------
    print("\n[A/C] 探针红→开窗409→冲突桶写明缺失→水位不偷加")
    call("POST", "/slots/S-ETL-02/active", {"active": False})
    st, probe = call("GET", "/windows/W-FACT-01/ready")
    check("缺依赖探针不得绿", probe["ready"] is False, probe)
    st, before = call("GET", "/watermarks")
    st, resp = call("POST", "/leases/open", {"window_code": "W-FACT-01"})
    check("缺依赖开窗 409", st == 409, resp)
    missing = resp["detail"]["missing"]
    check("409 写明缺失上游", any(m["resource_code"] == "S-ETL-02" for m in missing), resp)
    st, after = call("GET", "/watermarks")
    check("失败不偷加 open_leases 水位",
          after["watermarks"] and _wm(after, "open_leases") == _wm(before, "open_leases"),
          (before, after))
    check("失败无 open 租约残留", after["actual_open_leases"] == before["actual_open_leases"], after)
    check("冲突计数+1 且与冲突桶实数一致",
          _wm(after, "conflict_count") == _wm(before, "conflict_count") + 1
          and after["actual_conflicts"] == _wm(after, "conflict_count"), after)
    st, conflicts = call("GET", "/conflicts")
    c_rows = [c for c in conflicts if c["window_code"] == "W-FACT-01"]
    check("冲突桶有行且 reason 指认资源", len(c_rows) >= 1 and "S-ETL-02" in c_rows[0]["reason"], c_rows)
    st, wins = call("GET", "/windows")
    wf = next(w for w in wins if w["code"] == "W-FACT-01")
    check("失败后批窗仍 draft", wf["status"] == "draft" and wf["readiness"]["ready"] is False, wf)
    call("POST", "/slots/S-ETL-02/active", {"active": True})

    # ---------- 夹具 B：成功路径同事务自洽 ----------
    print("\n[B] 开窗成功 → 租约/批窗/水位/占用索引同事务自洽")
    st, ok = call("POST", "/leases/open", {"window_code": "W-DIM-01"})
    check("齐套开窗 200", st == 200 and ok["ok"] is True, ok)
    st, leases = call("GET", "/leases")
    lease = next(l for l in leases if l["lease_no"] == ok["lease_no"])
    check("租约已落 open", lease["status"] == "open" and lease["window_code"] == "W-DIM-01", lease)
    st, wm = call("GET", "/watermarks")
    check("水位=实际 open 租约=live 批窗",
          _wm(wm, "open_leases") == wm["actual_open_leases"] == wm["actual_live_sessions"] == 1, wm)
    st, slots = call("GET", "/slots")
    s1 = next(s for s in slots if s["code"] == "S-ETL-01")
    check("资源页占用索引 +1", s1["open_occupancy"] == 1, s1)
    st, dash = call("GET", "/dashboard")
    check("总览在途=1 且水位一致", dash["open_leases"] == 1 and dash["watermarks_consistent"] is True, dash)
    check("总览就绪数实时（live 窗也算闭包齐）",
          dash["ready_windows"] == 4 and dash["ready_all"] is True, dash)

    # ---------- 占用冲突：重叠窗探针红、开窗409、冲突桶有行 ----------
    print("\n[A2] 重叠占用 → 探针红且与开窗同闭包、冲突桶落行")
    st, created = call("POST", "/windows", {
        "code": "W-DIM-DUP", "title": "冲突试窗", "subject": "ETL",
        "slot_code": "S-ETL-01", "executor_code": "E-BI-01",
        "day": "2026-11-20", "start_min": 540, "end_min": 630})
    check("建重叠窗 200", st == 200, created)
    st, pr = call("GET", "/windows/W-DIM-DUP/ready")
    check("重叠窗探针红（不再假绿）", pr["ready"] is False
          and any("L-20261120-0001" in x or "占用" in x for x in pr["reasons"]), pr)
    st, wm_before = call("GET", "/watermarks")
    st, rej = call("POST", "/leases/open", {"window_code": "W-DIM-DUP"})
    check("重叠开窗 409", st == 409, rej)
    st, wm_after = call("GET", "/watermarks")
    check("409 不偷水位", _wm(wm_after, "open_leases") == _wm(wm_before, "open_leases")
          and wm_after["actual_open_leases"] == 1, wm_after)
    st, conflicts = call("GET", "/conflicts")
    check("重叠冲突落桶且指认算力槽",
          any(c["window_code"] == "W-DIM-DUP" and c["resource_code"] == "S-ETL-01" for c in conflicts),
          conflicts)

    # ---------- 夹具 E：并发双探针 / 双开窗 ----------
    print("\n[E] 并发双探针不双声明；并发双开窗串行只成一单")
    probe_out: list[dict] = []

    def probe():
        probe_out.append(call("GET", "/windows/W-RPT-01/ready")[1])

    ts = [threading.Thread(target=probe) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("双探针同结果（无两套声明）",
          all(p["ready"] == probe_out[0]["ready"] for p in probe_out)
          and probe_out[0]["ready"] is True, probe_out)

    call("POST", "/leases/close", {"lease_no": ok["lease_no"]})
    open_out: list[tuple[int, dict]] = []

    def do_open(code):
        open_out.append(call("POST", "/leases/open", {"window_code": code}))

    t1 = threading.Thread(target=do_open, args=("W-RPT-01",))
    t2 = threading.Thread(target=do_open, args=("W-RPT-02",))
    t1.start(); t2.start(); t1.join(); t2.join()
    codes = [s for s, _ in open_out]
    check("两不同窗并发开窗皆 200", codes == [200, 200], open_out)
    st, wm = call("GET", "/watermarks")
    check("并发后水位=实租约=live 数=2",
          _wm(wm, "open_leases") == wm["actual_open_leases"] == wm["actual_live_sessions"] == 2, wm)

    # 同窗并发：只成一单
    st, made = call("POST", "/windows", {
        "code": "W-RACE", "title": "竞态窗", "subject": "BI",
        "slot_code": "S-BI-01", "executor_code": "E-BI-02",
        "day": "2026-11-21", "start_min": 600, "end_min": 660})
    assert st == 200, made
    race_out: list[tuple[int, dict]] = []

    def race_open():
        race_out.append(call("POST", "/leases/open", {"window_code": "W-RACE"}))

    r1 = threading.Thread(target=race_open)
    r2 = threading.Thread(target=race_open)
    r1.start(); r2.start(); r1.join(); r2.join()
    statuses = sorted(s for s, _ in race_out)
    check("同窗并发开窗一成一拒", statuses == [200, 409], race_out)
    st, leases = call("GET", "/leases")
    check("被拒方无重复租约",
          len([l for l in leases if l["window_code"] == "W-RACE"]) == 1, leases)
    st, wm = call("GET", "/watermarks")
    check("竞态后水位仍与实数一致（无偷加）", wm["consistent"] is True, wm)

    # ---------- 关窗释放对账 ----------
    print("\n[F] 关窗释放：租约/批窗/水位同事务回落")
    open_leases = call("GET", "/leases")[1]
    for l in open_leases:
        if l["status"] == "open":
            st, cl = call("POST", "/leases/close", {"lease_no": l["lease_no"]})
            check(f"关窗 {l['lease_no']} 200", st == 200, cl)
    st, wm = call("GET", "/watermarks")
    check("全部关闭后水位归零且一致",
          _wm(wm, "open_leases") == 0 and wm["actual_open_leases"] == 0
          and wm["actual_live_sessions"] == 0 and wm["consistent"], wm)
    st, dash = call("GET", "/dashboard")
    check("总览终态水位一致；占用释放后重叠窗探针如实回绿（重放无缓存）",
          dash["watermarks_consistent"] is True
          and dash["unready"] == []
          and dash["ready_windows"] == dash["total_windows"]
          and dash["ready_all"] is True, dash)

    print(f"\n==== {PASS} PASS / {FAIL} FAIL ====")
    raise SystemExit(1 if FAIL else 0)


def _wm(payload: dict, key: str) -> int:
    return next((int(r["value"]) for r in payload["watermarks"] if r["key"] == key), 0)


if __name__ == "__main__":
    main()
