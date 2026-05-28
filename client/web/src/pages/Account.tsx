import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { ApiKeyCreated, ApiKeyInfo, UsageResponse } from "../api/types";

export default function Account() {
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [newKey, setNewKey] = useState<ApiKeyCreated | null>(null);
  const [keyName, setKeyName] = useState("");
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    api.usage().then(setUsage).catch(() => undefined);
    api.listKeys().then(setKeys).catch(() => undefined);
  }
  useEffect(refresh, []);

  async function createKey(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const created = await api.createKey(keyName.trim() || "default");
      setNewKey(created);
      setKeyName("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create key");
    }
  }

  async function revoke(prefix: string) {
    await api.revokeKey(prefix).catch(() => undefined);
    refresh();
  }

  async function upgrade(plan: "pro" | "team") {
    try {
      const { url } = await api.checkout(plan);
      window.location.href = url;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Billing unavailable");
    }
  }

  const pct =
    usage && usage.quota ? Math.min(100, Math.round((usage.used / usage.quota) * 100)) : 0;

  return (
    <>
      <div className="page-head enter">
        <span className="kicker">Workspace</span>
        <h1>Account</h1>
        <p>Plan, usage, and programmatic access.</p>
      </div>

      {error && <div className="error-note enter">{error}</div>}

      <div className="grid-2">
        <div className="panel enter">
          <div className="panel-title">Plan &amp; usage</div>
          {usage ? (
            <>
              <div className="spread">
                <div>
                  <div className="bignum">{usage.used}</div>
                  <div className="muted mono" style={{ fontSize: 11, marginTop: 4 }}>
                    memos · {usage.billing_period}
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className="kicker">Current plan</div>
                  <div className="serif" style={{ fontSize: 28, textTransform: "capitalize" }}>
                    {usage.plan}
                  </div>
                </div>
              </div>
              <div className="meter">
                <span style={{ width: `${pct}%` }} />
              </div>
              <div className="muted" style={{ fontSize: 13 }}>
                {usage.quota === null
                  ? "Unlimited memos on this plan."
                  : `${usage.used} of ${usage.quota} this period`}
              </div>

              {usage.plan !== "enterprise" && (
                <div className="row" style={{ marginTop: 22 }}>
                  {usage.plan !== "pro" && (
                    <button className="btn btn-gold btn-sm" onClick={() => upgrade("pro")}>
                      Upgrade to Pro · $29
                    </button>
                  )}
                  <button className="btn btn-ghost btn-sm" onClick={() => upgrade("team")}>
                    Team · $99
                  </button>
                </div>
              )}
            </>
          ) : (
            <p className="muted">Loading…</p>
          )}
        </div>

        <div className="panel enter">
          <div className="panel-title">API keys</div>
          <p className="muted" style={{ fontSize: 13, marginBottom: 16 }}>
            Use a key with the <span className="mono">theory-y</span> CLI or the SDK.
          </p>

          {newKey && (
            <div style={{ marginBottom: 18 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                Copy this now — it won't be shown again:
              </div>
              <div className="key-chip">{newKey.api_key}</div>
            </div>
          )}

          <form onSubmit={createKey} className="row" style={{ marginBottom: 18 }}>
            <input
              className="input"
              placeholder="Key name (e.g. ci, laptop)"
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
            />
            <button className="btn btn-gold btn-sm" style={{ whiteSpace: "nowrap" }}>
              + New key
            </button>
          </form>

          {keys.length === 0 ? (
            <p className="muted" style={{ fontSize: 13 }}>
              No keys yet.
            </p>
          ) : (
            <table className="rows">
              <tbody>
                {keys.map((k) => (
                  <tr key={k.prefix}>
                    <td className="mono" style={{ color: "var(--gold-lt)" }}>
                      {k.prefix}
                    </td>
                    <td>{k.name}</td>
                    <td style={{ textAlign: "right" }}>
                      {k.revoked ? (
                        <span className="muted mono" style={{ fontSize: 12 }}>
                          revoked
                        </span>
                      ) : (
                        <button className="btn btn-ghost btn-sm" onClick={() => revoke(k.prefix)}>
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}
