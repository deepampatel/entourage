/**
 * Root application component with routing.
 *
 * Learn: Uses React Router v7 for page navigation.
 * Auth gated — shows login page until JWT is obtained.
 * Team selection is managed via local state.
 */

import { useState } from "react";
import { Routes, Route, NavLink, Navigate } from "react-router-dom";
import { getToken, clearToken } from "./api/client";
import { useOrgs, useTeams } from "./hooks/useApi";
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

  // Auto-select first org and team
  if (orgs?.length && !orgId) {
    setOrgId(orgs[0].id);
  }
  if (teams?.length && !teamId) {
    setTeamId(teams[0].id);
  }

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
        </div>

        {/* Org selector */}
        {orgs && orgs.length > 1 && (
          <div className="sidebar-section">
            <label className="sidebar-label">Organization</label>
            <select
              className="org-select"
              value={orgId}
              onChange={(e) => {
                setOrgId(e.target.value);
                setTeamId("");
              }}
            >
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Team selector */}
        <div className="sidebar-section">
          <label className="sidebar-label">Team</label>
          {teams?.length ? (
            <select
              className="team-select"
              value={teamId}
              onChange={(e) => setTeamId(e.target.value)}
            >
              {teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          ) : (
            <span className="sidebar-empty">No teams</span>
          )}
        </div>

        {/* Navigation */}
        <div className="sidebar-nav">
          <NavLink to="/dashboard" className="nav-link">
            Dashboard
          </NavLink>
          <NavLink to="/runs" className="nav-link">
            Runs
          </NavLink>
          <NavLink to="/tasks" className="nav-link">
            Tasks
          </NavLink>
          <NavLink to="/requests" className="nav-link">
            Requests
          </NavLink>
          <NavLink to="/analytics" className="nav-link">
            Analytics
          </NavLink>
          <NavLink to="/settings" className="nav-link">
            Settings
          </NavLink>
          <NavLink to="/manage" className="nav-link">
            Manage
          </NavLink>
        </div>

        <div className="sidebar-footer">
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
                element={<Settings teamId={teamId} />}
              />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
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
