/**
 * Root application component with routing.
 *
 * Learn: Uses React Router v7 for page navigation.
 * Auth gated — shows login page until JWT is obtained.
 * Team selection is managed via local state.
 */

import { useEffect, useState } from "react";
import { Routes, Route, NavLink, Navigate } from "react-router-dom";
import { getToken, clearToken } from "./api/client";
import { useOrgs, useTeams } from "./hooks/useApi";
import { useGlobalKeyboard } from "./hooks/useKeyboard";
import { Analytics } from "./pages/Analytics";
import { Dashboard } from "./pages/Dashboard";
import { HumanRequests } from "./pages/HumanRequests";
import { Login } from "./pages/Login";
import { Manage } from "./pages/Manage";
import { Settings } from "./pages/Settings";
import { TaskDetail } from "./pages/TaskDetail";
import { Runs } from "./pages/Runs";
import { Tasks } from "./pages/Tasks";
import "./styles/index.css";

function OnboardingChecklist({ hasOrgs, hasTeams }: { hasOrgs: boolean; hasTeams: boolean }) {
  const steps = [
    { done: hasOrgs, label: "Create an Organization", desc: "Your top-level workspace" },
    { done: hasTeams, label: "Create a Team", desc: "A project with its own agents" },
    { done: false, label: "Add Agents", desc: "AI engineers that write code" },
    { done: false, label: "Create a Run", desc: "Describe what you want built" },
  ];

  return (
    <div className="empty-state-page">
      <h2>Welcome to Entourage</h2>
      <p className="onboarding-subtitle">
        Your AI agent team that plans, builds, reviews, and ships code.
      </p>
      <div className="onboarding-checklist">
        <h3>Get Started</h3>
        {steps.map((step, i) => (
          <div key={i} className={`onboarding-step${step.done ? " completed" : ""}`}>
            <span className="onboarding-step-icon">
              {step.done ? "\u2705" : `${i + 1}`}
            </span>
            <div>
              <span className="onboarding-step-label">{step.label}</span>
              <span className="onboarding-step-desc"> — {step.desc}</span>
            </div>
          </div>
        ))}
      </div>
      <NavLink
        to="/manage"
        className="manage-btn manage-btn-primary"
        style={{ display: "inline-block", marginTop: "1.5rem", textDecoration: "none" }}
      >
        Go to Setup
      </NavLink>
    </div>
  );
}

function AuthenticatedApp() {
  const { data: orgs } = useOrgs();
  const [orgId, setOrgId] = useState<string>("");
  const { data: teams } = useTeams(orgId || undefined);
  const [teamId, setTeamId] = useState<string>("");

  // Initialize theme from localStorage or system preference
  useState(() => {
    const saved = localStorage.getItem("theme");
    if (saved) {
      document.documentElement.setAttribute("data-theme", saved);
    } else if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
      document.documentElement.setAttribute("data-theme", "dark");
    }
    // Request browser notification permission
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
  });

  // Auto-select first org, last team (in useEffect, not during render)
  useEffect(() => {
    if (orgs?.length && !orgId) {
      setOrgId(orgs[0].id);
    }
  }, [orgs, orgId]);

  useEffect(() => {
    if (teams?.length && !teamId) {
      setTeamId(teams[teams.length - 1].id);
    }
  }, [teams, teamId]);

  // Keyboard shortcuts (g+d=Dashboard, g+r=Runs, /=search, Escape=close)
  useGlobalKeyboard();

  const handleLogout = () => {
    clearToken();
    window.location.reload();
  };

  return (
    <div className="app">
      {/* Sidebar */}
      <nav className="sidebar">
        <div className="sidebar-brand">
          <h1>Entourage</h1>
          {teams && teams.length > 1 ? (
            <select
              className="sidebar-team-select"
              value={teamId}
              onChange={(e) => setTeamId(e.target.value)}
            >
              {teams.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          ) : (
            teams?.[0] && <span className="sidebar-team-name">{teams[0].name}</span>
          )}
        </div>

        {/* Navigation — 3 pages only */}
        <div className="sidebar-nav">
          <NavLink to="/runs" className="nav-link">
            Runs
          </NavLink>
          <NavLink to="/settings" className="nav-link">
            Settings
          </NavLink>
          <NavLink to="/analytics" className="nav-link">
            Analytics
          </NavLink>
        </div>

        <div className="sidebar-footer">
          <button
            className="theme-toggle"
            onClick={() => {
              const html = document.documentElement;
              const current = html.getAttribute("data-theme") || "light";
              const next = current === "dark" ? "light" : "dark";
              html.setAttribute("data-theme", next);
              localStorage.setItem("theme", next);
            }}
            title="Toggle theme"
          >
            {typeof window !== "undefined" &&
             document.documentElement.getAttribute("data-theme") === "dark"
              ? "☀ Light"
              : "☾ Dark"}
          </button>
          <button className="logout-btn" onClick={handleLogout}>
            Logout
          </button>
        </div>
      </nav>

      {/* Main content */}
      <main className="main-content">
        <Routes>
          <Route
            path="/manage"
            element={<Manage orgId={orgId} onOrgChange={setOrgId} />}
          />
          {teamId ? (
            <>
              <Route
                path="/dashboard"
                element={<Dashboard teamId={teamId} />}
              />
              <Route
                path="/runs"
                element={<Runs teamId={teamId} />}
              />
              <Route path="/tasks" element={<Tasks teamId={teamId} />} />
              <Route
                path="/tasks/:taskId"
                element={<TaskDetail teamId={teamId} />}
              />
              <Route
                path="/requests"
                element={<HumanRequests teamId={teamId} />}
              />
              <Route
                path="/analytics"
                element={<Analytics teamId={teamId} />}
              />
              <Route
                path="/settings"
                element={<Settings teamId={teamId} orgId={orgId} />}
              />
              <Route path="*" element={<Navigate to="/runs" replace />} />
            </>
          ) : (
            <Route
              path="*"
              element={<OnboardingChecklist hasOrgs={!!orgs?.length} hasTeams={!!teams?.length} />}
            />
          )}
        </Routes>
      </main>
    </div>
  );
}

function App() {
  const [authed, setAuthed] = useState(!!getToken());

  if (!authed) {
    return <Login onLogin={() => setAuthed(true)} />;
  }

  return <AuthenticatedApp />;
}

export default App;
