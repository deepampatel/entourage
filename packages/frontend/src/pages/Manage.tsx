/**
 * Organization & Team management page.
 *
 * CRUD for orgs, teams, and agents — lets users create new
 * workspaces and add agents from the dashboard.
 */

import { useState } from "react";
import {
  useOrgs,
  useCreateOrg,
  useTeams,
  useCreateTeam,
  useAgents,
  useCreateAgent,
} from "../hooks/useApi";
import { useToast } from "../components/Toast";

const ROLE_DESCRIPTIONS: Record<string, string> = {
  engineer: "Writes code, runs tests, completes tasks",
  reviewer: "Reviews code changes, catches bugs",
  manager: "Breaks down work, coordinates engineers",
};

const MODEL_DESCRIPTIONS: Record<string, string> = {
  "claude-sonnet-4-20250514": "Balanced \u2014 good for most tasks",
  "claude-opus-4-20250514": "Most capable \u2014 complex architecture",
  "claude-haiku-4-20250414": "Fast & cheap \u2014 simple fixes",
};

// ─── Slug helper ────────────────────────────────────────

function toSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

// ─── Create Org Form ────────────────────────────────────

function CreateOrgForm({ onCreated }: { onCreated?: () => void }) {
  const [name, setName] = useState("");
  const createOrg = useCreateOrg();
  const { showToast } = useToast();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    createOrg.mutate(
      { name: name.trim(), slug: toSlug(name) },
      {
        onSuccess: () => {
          setName("");
          showToast("Organization created!", "success");
          onCreated?.();
        },
      }
    );
  };

  return (
    <form className="manage-form" onSubmit={handleSubmit}>
      <input
        type="text"
        placeholder="Organization name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="manage-input"
      />
      <button
        type="submit"
        className="manage-btn manage-btn-primary"
        disabled={createOrg.isPending || !name.trim()}
      >
        {createOrg.isPending ? "Creating..." : "Create Org"}
      </button>
      {createOrg.isError && (
        <span className="manage-error">{createOrg.error.message}</span>
      )}
    </form>
  );
}

// ─── Create Team Form ───────────────────────────────────

function CreateTeamForm({ orgId }: { orgId: string }) {
  const [name, setName] = useState("");
  const createTeam = useCreateTeam(orgId);
  const { showToast } = useToast();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    createTeam.mutate(
      { name: name.trim(), slug: toSlug(name) },
      {
        onSuccess: () => {
          setName("");
          showToast("Team created! Now add an agent below.", "success");
        },
      }
    );
  };

  return (
    <form className="manage-form" onSubmit={handleSubmit}>
      <input
        type="text"
        placeholder="Team name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="manage-input"
      />
      <button
        type="submit"
        className="manage-btn manage-btn-primary"
        disabled={createTeam.isPending || !name.trim()}
      >
        {createTeam.isPending ? "Creating..." : "Create Team"}
      </button>
      {createTeam.isError && (
        <span className="manage-error">{createTeam.error.message}</span>
      )}
    </form>
  );
}

// ─── Create Agent Form ──────────────────────────────────

function CreateAgentForm({ teamId }: { teamId: string }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState("engineer");
  const [model, setModel] = useState("claude-sonnet-4-20250514");
  const createAgent = useCreateAgent(teamId);
  const { showToast } = useToast();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    createAgent.mutate(
      {
        name: name.trim(),
        role,
        model,
        config: { description: `${role} agent` },
      },
      {
        onSuccess: () => {
          setName("");
          showToast("Agent added to team!", "success");
        },
      }
    );
  };

  return (
    <div>
      <form className="manage-form" onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="Agent name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="manage-input"
        />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="manage-select"
        >
          <option value="engineer">Engineer</option>
          <option value="reviewer">Reviewer</option>
          <option value="manager">Manager</option>
        </select>
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="manage-select"
        >
          <option value="claude-sonnet-4-20250514">Claude Sonnet 4</option>
          <option value="claude-opus-4-20250514">Claude Opus 4</option>
          <option value="claude-haiku-4-20250414">Claude Haiku 4</option>
        </select>
        <button
          type="submit"
          className="manage-btn manage-btn-primary"
          disabled={createAgent.isPending || !name.trim()}
        >
          {createAgent.isPending ? "Adding..." : "Add Agent"}
        </button>
        {createAgent.isError && (
          <span className="manage-error">{createAgent.error.message}</span>
        )}
      </form>
      <div className="form-help-row">
        <span className="form-help">{ROLE_DESCRIPTIONS[role]}</span>
        <span className="form-help">{MODEL_DESCRIPTIONS[model]}</span>
      </div>
    </div>
  );
}

// ─── Team Detail Panel ──────────────────────────────────

function TeamPanel({
  teamId,
  teamName,
}: {
  teamId: string;
  teamName: string;
}) {
  const { data: agents } = useAgents(teamId);

  return (
    <div className="manage-card">
      <div className="manage-card-header">
        <h3>{teamName}</h3>
        <span className="manage-badge">{agents?.length ?? 0} agents</span>
      </div>

      {agents && agents.length > 0 && (
        <div className="manage-agent-list">
          {agents.map((a) => (
            <div key={a.id} className="manage-agent-row">
              <span className="manage-agent-name">{a.name}</span>
              <span className={`manage-role manage-role-${a.role}`}>
                {a.role}
              </span>
              <span className="manage-agent-model">{a.model.split("-").slice(0, 2).join(" ")}</span>
              <span className={`manage-status manage-status-${a.status}`}>
                {a.status}
              </span>
            </div>
          ))}
        </div>
      )}

      <CreateAgentForm teamId={teamId} />
    </div>
  );
}

// ─── Main Page ──────────────────────────────────────────

export function Manage({
  orgId,
  onOrgChange,
}: {
  orgId: string;
  onOrgChange: (id: string) => void;
}) {
  const { data: orgs } = useOrgs();
  const { data: teams } = useTeams(orgId || undefined);
  const [activeTab, setActiveTab] = useState<"teams" | "orgs">("teams");

  return (
    <div className="manage-page">
      <h1>Manage</h1>

      {/* Tab bar */}
      <div className="manage-tabs">
        <button
          className={`manage-tab ${activeTab === "teams" ? "active" : ""}`}
          onClick={() => setActiveTab("teams")}
        >
          Teams & Agents
        </button>
        <button
          className={`manage-tab ${activeTab === "orgs" ? "active" : ""}`}
          onClick={() => setActiveTab("orgs")}
        >
          Organizations
        </button>
      </div>

      {/* Teams & Agents tab */}
      {activeTab === "teams" && (
        <div className="manage-section">
          <div className="manage-section-header">
            <h2>Teams</h2>
            <p className="form-help">Teams group agents working on the same project.</p>
          </div>

          {teams && teams.length > 0 ? (
            <div className="manage-grid">
              {teams.map((t) => (
                <TeamPanel key={t.id} teamId={t.id} teamName={t.name} />
              ))}
            </div>
          ) : (
            <div className="manage-empty-state">
              <p className="manage-empty">No teams yet</p>
              <p className="form-help">Create a team to start adding agents that will execute your pipelines.</p>
            </div>
          )}

          {orgId && (
            <>
              <h2 className="manage-sub-heading">Create Team</h2>
              <CreateTeamForm orgId={orgId} />
            </>
          )}
        </div>
      )}

      {/* Organizations tab */}
      {activeTab === "orgs" && (
        <div className="manage-section">
          <div className="manage-section-header">
            <h2>Organizations</h2>
            <p className="form-help">Organizations are your top-level workspace. Start with one.</p>
          </div>

          {orgs && orgs.length > 0 ? (
            <div className="manage-org-list">
              {orgs.map((o) => (
                <div
                  key={o.id}
                  className={`manage-org-row ${o.id === orgId ? "active" : ""}`}
                  onClick={() => onOrgChange(o.id)}
                >
                  <span className="manage-org-name">{o.name}</span>
                  <span className="manage-org-slug">{o.slug}</span>
                  {o.id === orgId && (
                    <span className="manage-badge">Active</span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="manage-empty-state">
              <p className="manage-empty">No organizations yet</p>
              <p className="form-help">Create an organization to group your teams and projects.</p>
            </div>
          )}

          <h2 className="manage-sub-heading">Create Organization</h2>
          <CreateOrgForm onCreated={() => setActiveTab("teams")} />
        </div>
      )}
    </div>
  );
}
