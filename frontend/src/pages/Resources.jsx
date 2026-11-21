import { useEffect, useState } from "react";
import { api } from "../api";

export default function Resources() {
  const [slots, setSlots] = useState([]);
  const [executors, setExecutors] = useState([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  async function load() {
    const [r, t] = await Promise.all([api.slots(), api.executors()]);
    setSlots(r);
    setExecutors(t);
  }

  useEffect(() => {
    load().catch((e) => setErr(e.message));
  }, []);

  async function toggle(kind, row) {
    setMsg("");
    setErr("");
    try {
      if (kind === "slot") {
        await api.setSlotActive(row.code, !row.active);
      } else {
        await api.setExecutorActive(row.code, !row.active);
      }
      setMsg(`${row.code} 已${row.active ? "停用" : "启用"}；探针与开窗下次重放立即生效`);
      await load();
    } catch (e) {
      setErr(e.message);
    }
  }

  if (err) return <div className="msg err">{err}</div>;

  return (
    <>
      {msg && <div className="msg">{msg}</div>}
      <section className="panel">
        <h2>算力槽（依赖维护 · 占用索引实时对账 leases）</h2>
        <table>
          <thead>
            <tr>
              <th>编码</th>
              <th>名称</th>
              <th>容量</th>
              <th>状态</th>
              <th>open 租约占用</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {slots.map((r) => (
              <tr key={r.code}>
                <td>{r.code}</td>
                <td>{r.name}</td>
                <td>{r.capacity}</td>
                <td>
                  <span className={`tag ${r.active ? "live" : "bad"}`}>
                    {r.active ? "启用" : "停用"}
                  </span>
                </td>
                <td>{r.open_occupancy}</td>
                <td>
                  <button className="secondary" onClick={() => toggle("slot", r)}>
                    {r.active ? "停用" : "启用"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="panel">
        <h2>执行器（依赖维护 · 占用索引实时对账 leases）</h2>
        <table>
          <thead>
            <tr>
              <th>编码</th>
              <th>名称</th>
              <th>作业类型</th>
              <th>状态</th>
              <th>open 租约占用</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {executors.map((t) => (
              <tr key={t.code}>
                <td>{t.code}</td>
                <td>{t.name}</td>
                <td>{t.subject}</td>
                <td>
                  <span className={`tag ${t.active ? "live" : "bad"}`}>
                    {t.active ? "启用" : "停用"}
                  </span>
                </td>
                <td>{t.open_occupancy}</td>
                <td>
                  <button className="secondary" onClick={() => toggle("exe", t)}>
                    {t.active ? "停用" : "启用"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
