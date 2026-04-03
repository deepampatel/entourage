/**
 * Settings page — team configuration form.
 *
 * Learn: Displays and edits team settings via GET/PATCH /settings/teams/{id}.
 * Uses controlled form inputs with local state, submitted via mutation.
 * Phase 3D adds a Security section for network allowlist and security mode.
 */

import { useState, useEffect, lazy, Suspense } from "react";
import { useTeamSettings, useUpdateTeamSettings } from "../hooks/useApi";
import { useToast } from "../components/Toast";
import "../styles/settings.css";

interface SettingsProps {
  teamId: string;
}

function TeamConfig({ teamId }: SettingsProps) {
  const { data: teamSettings, isLoading } = useTeamSettings(teamId);
  const updateMut = useUpdateTeamSettings(teamId);
  const { showToast } = useToast();

  const [form, setForm] = useState<Record<string, unknown>>({});
  const [saved, setSaved] = useState(false);
  const [newDomain, setNewDomain] = useState("");

  useEffect(() => {
    if (teamSettings?.settings) {
      setForm(teamSettings.settings);
    }
  }, [teamSettings]);

  const handleChange = (key: string, value: unknown) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    updateMut.mutate(form, {
      onSuccess: () => {
        setSaved(true);
        showToast("Settings saved!", "success");
      },
    });
  };

  const networkAllowlist = (form.network_allowlist as string[]) ?? [];

  const handleAddDomain = () => {
    const domain = newDomain.trim();
    if (domain && !networkAllowlist.includes(domain)) {
      handleChange("network_allowlist", [...networkAllowlist, domain]);
      setNewDomain("");
    }
  };

  const handleRemoveDomain = (domain: string) => {
    handleChange(
      "network_allowlist",
      networkAllowlist.filter((d) => d !== domain)
    );
  };

  if (isLoading) {
    return <div className="loading">Loading settings...</div>;
  }

  return (
    <div className="settings-page">
      <h1>Team Settings</h1>
      {teamSettings && (
        <p className="settings-team-name">{teamSettings.team_name}</p>
      )}

      <form className="settings-form" onSubmit={handleSubmit}>
        {/* Cost Limits */}
        <div className="settings-section">
          <h2>Cost Controls</h2>
          <p className="form-help">Limit how much agents can spend on API calls.</p>
          <div className="settings-field">
            <label>Daily Cost Limit (USD)</label>
            <input
              type="number"
              step="0.01"
              value={(form.daily_cost_limit_usd as number) ?? ""}
              onChange={(e) =>
                handleChange(
                  "daily_cost_limit_usd",
                  e.target.value ? Number(e.target.value) : null
                )
              }
              placeholder="No limit"
            />
          </div>
          <div className="settings-field">
            <label>Per-Task Cost Limit (USD)</label>
            <input
              type="number"
              step="0.01"
              value={(form.task_cost_limit_usd as number) ?? ""}
              onChange={(e) =>
                handleChange(
                  "task_cost_limit_usd",
                  e.target.value ? Number(e.target.value) : null
                )
              }
              placeholder="No limit"
            />
          </div>
        </div>

        {/* Agent Configuration */}
        <div className="settings-section">
          <h2>Agent Defaults</h2>
          <p className="form-help">Default configuration for new agents.</p>
          <div className="settings-field">
            <label>Default Model</label>
            <input
              type="text"
              value={(form.default_model as string) ?? ""}
              onChange={(e) =>
                handleChange("default_model", e.target.value || null)
              }
              placeholder="claude-sonnet-4-20250514"
            />
          </div>
          <div className="settings-field">
            <label>Branch Prefix</label>
            <input
              type="text"
              value={(form.branch_prefix as string) ?? ""}
              onChange={(e) =>
                handleChange("branch_prefix", e.target.value || null)
              }
              placeholder="task/"
            />
          </div>
        </div>

        {/* Workflow */}
        <div className="settings-section">
          <h2>Workflow</h2>
          <p className="form-help">Control the code review and merge process.</p>
          <div className="settings-field settings-toggle">
            <label>
              <input
                type="checkbox"
                checked={(form.require_review as boolean) ?? true}
                onChange={(e) =>
                  handleChange("require_review", e.target.checked)
                }
              />
              Require code review before merge
            </label>
          </div>
          <div className="settings-field settings-toggle">
            <label>
              <input
                type="checkbox"
                checked={(form.auto_merge as boolean) ?? false}
                onChange={(e) =>
                  handleChange("auto_merge", e.target.checked)
                }
              />
              Auto-merge after approval
            </label>
          </div>
        </div>

        {/* Security */}
        <div className="settings-section">
          <h2>Security</h2>
          <p className="form-help">Network access and file system restrictions for agents.</p>
          <div className="settings-field">
            <label>Security Mode</label>
            <select
              value={(form.security_mode as string) ?? "strict"}
              onChange={(e) => handleChange("security_mode", e.target.value)}
            >
              <option value="strict">Strict (block violations)</option>
              <option value="permissive">Permissive (log only)</option>
            </select>
          </div>

          <div className="settings-field">
            <label>Network Allowlist</label>
            <p className="settings-hint">
              Domains agents are allowed to access. Supports wildcards
              (*.github.com).
            </p>
            <div className="allowlist-editor">
              {networkAllowlist.map((domain) => (
                <div key={domain} className="allowlist-item">
                  <span className="allowlist-domain">{domain}</span>
                  <button
                    type="button"
                    className="allowlist-remove"
                    onClick={() => handleRemoveDomain(domain)}
                  >
                    x
                  </button>
                </div>
              ))}
              <div className="allowlist-add">
                <input
                  type="text"
                  value={newDomain}
                  onChange={(e) => setNewDomain(e.target.value)}
                  placeholder="e.g. *.github.com"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleAddDomain();
                    }
                  }}
                />
                <button
                  type="button"
                  className="allowlist-add-btn"
                  onClick={handleAddDomain}
                >
                  Add
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="settings-actions">
          <button
            type="submit"
            className="settings-save-btn"
            disabled={updateMut.isPending}
          >
            {updateMut.isPending ? "Saving..." : "Save Settings"}
          </button>
          {saved && <span className="settings-saved">Saved!</span>}
          {updateMut.isError && (
            <span className="settings-error">
              Error: {updateMut.error?.message}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}

// ─── Unified Settings Page (Config + Agents + Repos) ──

// Lazy load Manage to avoid circular deps
const ManageLazy = lazy(() =>
  import("./Manage").then((m) => ({ default: m.Manage }))
);

interface UnifiedSettingsProps {
  teamId: string;
  orgId: string;
}

export function Settings({ teamId, orgId }: UnifiedSettingsProps) {
  const [tab, setTab] = useState<"config" | "agents">("agents");

  return (
    <div className="settings-unified">
      <div className="settings-tabs">
        <button
          className={`settings-tab ${tab === "agents" ? "active" : ""}`}
          onClick={() => setTab("agents")}
        >
          Agents & Repos
        </button>
        <button
          className={`settings-tab ${tab === "config" ? "active" : ""}`}
          onClick={() => setTab("config")}
        >
          Configuration
        </button>
      </div>

      {tab === "agents" && (
        <Suspense fallback={<div className="loading">Loading...</div>}>
          <ManageLazy orgId={orgId} />
        </Suspense>
      )}

      {tab === "config" && <TeamConfig teamId={teamId} />}
    </div>
  );
}
