import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api";
import AnalyticsPage from "./pages/Analytics";
import CampaignDetail from "./pages/CampaignDetail";
import Campaigns from "./pages/Campaigns";
import DashboardPage from "./pages/Dashboard";
import Exports from "./pages/Exports";
import IdeasPage from "./pages/Ideas";
import MediaPage from "./pages/Media";
import ProjectDetail from "./pages/ProjectDetail";
import Projects from "./pages/Projects";
import Scripts from "./pages/Scripts";
import SettingsPage from "./pages/Settings";
import Submissions from "./pages/Submissions";
import Templates from "./pages/Templates";
import VoicePage from "./pages/Voice";

const NAV = [
  ["/dashboard", "Dashboard"],
  ["/campaigns", "Campaigns"],
  ["/media", "Media"],
  ["/ideas", "Ideas"],
  ["/scripts", "Scripts"],
  ["/voice", "Voice"],
  ["/projects", "Projects"],
  ["/templates", "Templates"],
  ["/exports", "Exports"],
  ["/submissions", "Submissions"],
  ["/analytics", "Analytics"],
  ["/settings", "Settings"],
] as const;

function BackendStatus() {
  const [state, setState] = useState<"checking" | "ok" | "down">("checking");
  const [version, setVersion] = useState("");
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const h = await api.get<{ version: string }>("/api/health");
        if (alive) {
          setState("ok");
          setVersion(h.version);
        }
      } catch {
        if (alive) setState("down");
      }
    };
    void check();
    const t = setInterval(check, 10_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  return (
    <div className="backend-status" data-testid="backend-status">
      Backend:{" "}
      {state === "ok" ? <span style={{ color: "var(--good)" }}>connected v{version}</span> : state === "down" ? <span style={{ color: "var(--bad)" }}>not reachable</span> : "checking…"}
    </div>
  );
}

export default function App() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">▶</span> Roblox Clip Factory
        </div>
        <nav className="nav">
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>
              {label}
            </NavLink>
          ))}
        </nav>
        <BackendStatus />
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/campaigns" element={<Campaigns />} />
          <Route path="/campaigns/:id" element={<CampaignDetail />} />
          <Route path="/media" element={<MediaPage />} />
          <Route path="/ideas" element={<IdeasPage />} />
          <Route path="/scripts" element={<Scripts />} />
          <Route path="/voice" element={<VoicePage />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/templates" element={<Templates />} />
          <Route path="/exports" element={<Exports />} />
          <Route path="/submissions" element={<Submissions />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
}
