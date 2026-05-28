import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";

export default function Login() {
  const { login, signup } = useAuth();
  const nav = useNavigate();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await signup(email, password);
      nav("/generate");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card enter">
        <div className="auth-brand">
          <div className="mark">
            Theory<b>Y</b>
          </div>
          <span className="kicker">Institutional Equity Research</span>
        </div>
        <div className="doc">
          <h2 style={{ fontSize: 26, marginBottom: 4 }}>
            {mode === "login" ? "Sign in" : "Create account"}
          </h2>
          <p style={{ color: "var(--slate-dk)", fontSize: 14, marginBottom: 22 }}>
            {mode === "login"
              ? "Access your research desk."
              : "Start with 5 memos per month, free."}
          </p>
          {error && <div className="error-note">{error}</div>}
          <form onSubmit={submit}>
            <div className="field">
              <label>Email</label>
              <input
                className="input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>
            <div className="field">
              <label>Password</label>
              <input
                className="input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
              />
            </div>
            <button className="btn btn-gold" style={{ width: "100%" }} disabled={busy}>
              {busy ? <span className="spin" /> : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>
        </div>
        <div className="toggle-row">
          {mode === "login" ? "New here? " : "Have an account? "}
          <button onClick={() => setMode(mode === "login" ? "signup" : "login")}>
            {mode === "login" ? "Create an account" : "Sign in"}
          </button>
        </div>
      </div>
    </div>
  );
}
