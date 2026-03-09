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
import { Pipelines } from "./pages/Pipelines";
import { Tasks } from "./pages/Tasks";
import "./styles/index.css";

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
          <NavLink to="/pipelines" className="nav-link">
            Pipelines
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
                path="/pipelines"
                element={<Pipelines teamId={teamId} />}
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
              element={
                <div className="empty-state-page">
                  <h2>Welcome to Entourage</h2>
                  <p>Create an organization and team to get started.</p>
                  <NavLink
                    to="/manage"
                    className="manage-btn manage-btn-primary"
                    style={{
                      display: "inline-block",
                      marginTop: "1rem",
                      textDecoration: "none",
                    }}
                  >
                    Go to Manage
                  </NavLink>
                </div>
              }
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
