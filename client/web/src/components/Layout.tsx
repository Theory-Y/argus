import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const NAV = [
  { to: "/generate", label: "Generate" },
  { to: "/history", label: "History" },
  { to: "/account", label: "Account" },
];

export default function Layout() {
  const { logout } = useAuth();
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="mark">
            Theory<b>Y</b>
          </span>
          <span className="tag">Research</span>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "active" : "")}>
              <span className="dot" />
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="foot">
          <button onClick={logout}>Sign out</button>
          <div style={{ marginTop: 10 }}>Institutional use only</div>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`pill ${status}`}>
      <span className="led" />
      {status}
    </span>
  );
}
