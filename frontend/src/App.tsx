import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useTheme } from "./lib/theme";
import { SyncButton } from "./components/SyncButton";
import { OverviewPage } from "./pages/Overview";
import { ActivitiesPage } from "./pages/Activities";
import { ActivityDetailPage } from "./pages/ActivityDetail";
import { TrendsPage } from "./pages/Trends";
import { useState } from "react";

const NAV = [
  { to: "/", label: "Overview", icon: "◎", end: true },
  { to: "/activities", label: "Activities", icon: "🏃", end: false },
  { to: "/trends", label: "Health trends", icon: "📈", end: false },
];

export function App() {
  const [theme, toggle] = useTheme();
  const { pathname } = useLocation();
  // Bump this to force child pages to refetch after a sync.
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="app">
      <aside className="sidebar">
      <div className="side-inner">
        <div className="brand">
          <span className="dot" />
          <span>mygarmin</span>
        </div>
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            aria-label={n.label}
            className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
          >
            <span className="ico" aria-hidden>
              {n.icon}
            </span>
            <span className="txt">{n.label}</span>
          </NavLink>
        ))}
        <div className="sidebar-foot">
          <SyncButton onDone={() => setRefreshKey((k) => k + 1)} />
          <button className="btn ghost" onClick={toggle}>
            {theme === "dark" ? "☀️ Light" : "🌙 Dark"}
          </button>
        </div>
        </div>
      </aside>

      <main className="main">
        <div className="content page" key={pathname}>
          <Routes>
            <Route path="/" element={<OverviewPage refreshKey={refreshKey} />} />
            <Route path="/activities" element={<ActivitiesPage />} />
            <Route path="/activities/:id" element={<ActivityDetailPage />} />
            <Route path="/trends" element={<TrendsPage />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
