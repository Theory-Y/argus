import { useEffect, useRef, useState } from "react";
import { api, ApiError, downloadMemo } from "../api/client";
import type { MemoFormat, MemoJob, TickersResponse } from "../api/types";
import { StatusPill } from "../components/Layout";

const FORMATS: MemoFormat[] = ["pdf", "md", "docx"];

export default function Generate() {
  const [universe, setUniverse] = useState<TickersResponse | null>(null);
  const [ticker, setTicker] = useState("");
  const [format, setFormat] = useState<MemoFormat>("pdf");
  const [job, setJob] = useState<MemoJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);

  useEffect(() => {
    api.tickers().then(setUniverse).catch(() => undefined);
    return () => {
      if (poll.current) window.clearInterval(poll.current);
    };
  }, []);

  const peers = universe?.competitor_map[ticker.toUpperCase()] ?? [];

  function startPolling(jobId: string) {
    if (poll.current) window.clearInterval(poll.current);
    poll.current = window.setInterval(async () => {
      try {
        const s = await api.memoStatus(jobId);
        setJob(s);
        if (s.status === "complete" || s.status === "failed") {
          if (poll.current) window.clearInterval(poll.current);
        }
      } catch {
        /* transient */
      }
    }, 2500);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const created = await api.createMemo(ticker.trim().toUpperCase(), format);
      setJob(created);
      startPolling(created.job_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start memo");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head enter">
        <span className="kicker">New research</span>
        <h1>Generate a memo</h1>
        <p>Five-section institutional analysis, grounded in live data — never fabricated.</p>
      </div>

      <div className="grid-2">
        <div className="doc enter">
          <form onSubmit={submit}>
            <div className="field">
              <label>Ticker</label>
              <input
                className="input ticker"
                list="universe"
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase())}
                placeholder="PCOR"
                maxLength={8}
                required
              />
              <datalist id="universe">
                {universe?.sector_tickers.map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
            </div>

            {peers.length > 0 && (
              <p style={{ color: "var(--slate-dk)", fontSize: 13, marginBottom: 18 }}>
                Peers: <span className="mono">{peers.join(" · ")}</span>
              </p>
            )}

            <div className="field">
              <label>Output format</label>
              <div className="segment">
                {FORMATS.map((f) => (
                  <button
                    type="button"
                    key={f}
                    className={f === format ? "on" : ""}
                    onClick={() => setFormat(f)}
                  >
                    {f}
                  </button>
                ))}
              </div>
            </div>

            {error && <div className="error-note" style={{ marginTop: 8 }}>{error}</div>}

            <button
              className="btn btn-gold"
              style={{ width: "100%", marginTop: 8 }}
              disabled={busy || !ticker.trim()}
            >
              {busy ? <span className="spin" /> : "Generate memo"}
            </button>
          </form>
        </div>

        <div className="panel enter">
          <div className="panel-title">Job monitor</div>
          {!job && (
            <p className="muted" style={{ fontSize: 14 }}>
              Submit a ticker to begin. Memos typically take under a minute to fetch data and
              write.
            </p>
          )}
          {job && (
            <div className="stack">
              <div className="spread">
                <span className="mono" style={{ fontSize: 18, color: "var(--gold-lt)" }}>
                  {ticker.toUpperCase()}
                </span>
                <StatusPill status={job.status} />
              </div>
              <div>
                <div className="progress">
                  <span style={{ width: `${job.progress}%` }} />
                </div>
                <div className="muted mono" style={{ fontSize: 11, marginTop: 8 }}>
                  {job.progress}% · job {job.job_id.slice(0, 8)}
                </div>
              </div>
              {job.status === "failed" && (
                <div className="error-note">{job.error ?? "Generation failed"}</div>
              )}
              {job.status === "complete" && (
                <div>
                  <div className="muted" style={{ fontSize: 13, marginBottom: 10 }}>
                    Ready to download:
                  </div>
                  <div className="row" style={{ flexWrap: "wrap" }}>
                    {job.formats.map((f) => (
                      <button
                        key={f}
                        className="btn btn-ghost btn-sm"
                        onClick={() =>
                          downloadMemo(job.job_id, f, `TheoryY_Memo_${ticker.toUpperCase()}.${f}`)
                        }
                      >
                        ↓ {f.toUpperCase()}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
