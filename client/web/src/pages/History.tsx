import { useEffect, useState } from "react";
import { api, downloadMemo } from "../api/client";
import type { MemoJob } from "../api/types";
import { StatusPill } from "../components/Layout";

export default function History() {
  const [jobs, setJobs] = useState<MemoJob[] | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.listMemos().then((j) => alive && setJobs(j)).catch(() => undefined);
    load();
    // refresh while anything is in flight
    const t = window.setInterval(load, 4000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  return (
    <>
      <div className="page-head enter">
        <span className="kicker">Archive</span>
        <h1>Memo history</h1>
        <p>Every memo you've generated, with one-click re-download.</p>
      </div>

      <div className="panel enter">
        {jobs && jobs.length === 0 && (
          <p className="muted" style={{ fontSize: 14 }}>
            No memos yet — head to Generate to create your first.
          </p>
        )}
        {jobs && jobs.length > 0 && (
          <table className="rows">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Job</th>
                <th style={{ textAlign: "right" }}>Download</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.job_id}>
                  <td className="tk">{j.ticker}</td>
                  <td>
                    <StatusPill status={j.status} />
                  </td>
                  <td className="mono muted">{j.progress}%</td>
                  <td className="mono muted" style={{ fontSize: 12 }}>
                    {j.job_id.slice(0, 8)}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <div className="row" style={{ justifyContent: "flex-end", flexWrap: "wrap" }}>
                      {j.formats.map((f) => (
                        <button
                          key={f}
                          className="btn btn-ghost btn-sm"
                          onClick={() => downloadMemo(j.job_id, f, `TheoryY_Memo_${j.ticker}.${f}`)}
                        >
                          {f.toUpperCase()}
                        </button>
                      ))}
                      {j.formats.length === 0 && <span className="muted">—</span>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {!jobs && <p className="muted">Loading…</p>}
      </div>
    </>
  );
}
