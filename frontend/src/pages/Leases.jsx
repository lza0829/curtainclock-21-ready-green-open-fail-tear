import { useEffect, useState } from "react";
import { api } from "../api";

function fmtMin(m) {
  const h = String(Math.floor(m / 60)).padStart(2, "0");
  const mm = String(m % 60).padStart(2, "0");
  return `${h}:${mm}`;
}

export default function Leases() {
  const [rows, setRows] = useState([]);
  const [wm, setWm] = useState(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function load() {
    const [leases, water] = await Promise.all([api.leases(), api.watermarks()]);
    setRows(leases);
    setWm(water);
  }

  useEffect(() => {
    load().catch((e) => setErr(e.message));
  }, []);

  async function closeOne(lease_no) {
    setMsg("");
    setErr("");
    try {
      const r = await api.closeLease(lease_no);
      setMsg(`已关窗释放 ${r.lease_no}；在途租约 ${r.open_leases}`);
      await load();
    } catch (e) {
      setErr(e.message);
    }
  }

  return (
    <section className="panel">
      <h2>租约</h2>
      {wm && (
        <p>
          <span className={`tag ${wm.consistent ? "live" : "bad"}`}>
            水位 {wm.watermarks.find((x) => x.key === "open_leases")?.value ?? 0}
            {" "}/ open 租约实数 {wm.actual_open_leases} / 占用批窗{" "}
            {wm.actual_live_sessions}
            {" — "}
            {wm.consistent ? "三方一致" : "不一致"}
          </span>
        </p>
      )}
      {msg && <div className="msg">{msg}</div>}
      {err && <div className="msg err">{err}</div>}
      <table>
        <thead>
          <tr>
            <th>租约号</th>
            <th>批窗</th>
            <th>资源</th>
            <th>时段</th>
            <th>状态</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.lease_no}>
              <td>{r.lease_no}</td>
              <td>{r.window_code}</td>
              <td>
                {r.slot_code} / {r.executor_code}
              </td>
              <td>
                {r.day} {fmtMin(r.start_min)}–{fmtMin(r.end_min)}
              </td>
              <td>{r.status === "open" ? "占用中" : "已释放"}</td>
              <td>
                <button
                  className="secondary"
                  disabled={r.status !== "open"}
                  onClick={() => closeOne(r.lease_no)}
                >
                  关窗释放
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
