import { useEffect, useState } from "react";
import { api } from "../api";

export default function Home() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .dashboard()
      .then(setD)
      .catch((e) => setErr(e.message));
  }, []);

  if (err) return <div className="msg err">{err}</div>;
  if (!d) return <div className="panel">加载中…</div>;

  return (
    <>
      <section className="panel">
        <h2>今日水位 · {d.fixture_day}</h2>
        <div className="stats">
          <div className="stat">
            在途租约（水位 / 实数）
            <b>
              {d.open_leases} / {d.actual_open_leases}
            </b>
          </div>
          <div className="stat">
            冲突计数（水位 / 实数）
            <b>
              {d.conflict_count} / {d.actual_conflicts}
            </b>
          </div>
          <div className="stat">
            占用中批窗
            <b>{d.live_sessions}</b>
          </div>
          <div className="stat">
            待开窗（其中就绪 {d.ready_draft}）
            <b>{d.draft_sessions}</b>
          </div>
        </div>
        <p style={{ marginTop: 12 }}>
          就绪重放：
          <span className={`tag ${d.ready_all ? "live" : "bad"}`}>
            {d.ready_windows}/{d.total_windows} 就绪
          </span>{" "}
          <span className={`tag ${d.watermarks_consistent ? "live" : "bad"}`}>
            水位与租约{d.watermarks_consistent ? "一致" : "不一致"}
          </span>
        </p>
      </section>

      <section className="panel">
        <h2>未就绪批窗（缺哪条上游逐条可查）</h2>
        {d.unready.length === 0 ? (
          <p>
            <span className="tag live">全部批窗依赖闭包齐备</span>
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>批窗</th>
                <th>缺失依赖 / 占用原因</th>
              </tr>
            </thead>
            <tbody>
              {d.unready.map((u) => (
                <tr key={u.window_code}>
                  <td>{u.window_code}</td>
                  <td>
                    {u.reasons.map((r) => (
                      <div key={r}>
                        <span className="tag bad">{r}</span>
                      </div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
