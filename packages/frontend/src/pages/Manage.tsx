/**
 * Manage page — team, agent, and repo management.
 *
 * Agents are editable inline: click to expand, change name/model/role.
 */

import { useState } from "react";
import {
  useTeams,
  useCreateTeam,
  useAgents,
  useCreateAgent,
  useUpdateAgent,
  useRepos,
  useRegisterRepo,
  useValidateRepo,
} from "../hooks/useApi";
import { useToast } from "../components/Toast";
import type { Agent } from "../api/types";

const ROLE_DESCRIPTIONS: Record<string, string> = {
  engineer: "Writes code, runs tests, completes tasks",
  reviewer: "Reviews code changes, catches bugs",
  manager: "Breaks down work, coordinates engineers",
};

const MODELS = [
  { value: "claude-sonnet-4-20250514", label: "Claude Sonnet 4", desc: "Balanced — good for most tasks" },
  { value: "claude-opus-4-20250514", label: "Claude Opus 4", desc: "Most capable — complex architecture" },
  { value: "claude-haiku-4-20250414", label: "Claude Haiku 4", desc: "Fast & cheap — simple fixes" },
];

function toSlug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

// ─── Agent Card (editable) ─────────────────────────────

function AgentCard({ agent, teamId }: { agent: Agent; teamId: string }) {
  const [expanded, setExpanded] = useState(false);
  const [name, setName] = useState(agent.name);
  const [model, setModel] = useState(agent.model);
  const [role, setRole] = useState(agent.role);
  const updateAgent = useUpdateAgent(teamId);
  const { showToast } = useToast();

  const isDirty = name !== agent.name || model !== agent.model || role !== agent.role;

  const handleSave = () => {
    const updates: Record<string, string> = {};
    if (name !== agent.name) updates.name = name;
    if (model !== agent.model) updates.model = model;
    if (role !== agent.role) updates.role = role;

    updateAgent.mutate(
      { agentId: agent.id, ...updates },
      {
        onSuccess: () => {
          showToast("Agent updated!", "success");
          setExpanded(false);
        },
      }
    );
  };

  const modelInfo = MODELS.find((m) => m.value === agent.model);

  return (
    <div className={`agent-manage-card ${expanded ? "expanded" : ""}`}>
      <div className="agent-manage-header" onClick={() => setExpanded(!expanded)}>
        <div className="agent-manage-name-row">
          <span className="agent-manage-name">{agent.name}</span>
          <span className={`manage-role manage-role-${agent.role}`}>{agent.role}</span>
          <span className={`manage-status manage-status-${agent.status}`}>{agent.status}</span>
        </div>
        <span className="agent-manage-model">{modelInfo?.label || agent.model}</span>
      </div>

      {expanded && (
        <div className="agent-manage-edit" onClick={(e) => e.stopPropagation()}>
          <div className="agent-edit-field">
            <label>Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="manage-input"
            />
          </div>

          <div className="agent-edit-field">
            <label>Role</label>
            <select value={role} onChange={(e) => setRole(e.target.value)} className="manage-select">
              <option value="engineer">Engineer</option>
              <option value="reviewer">Reviewer</option>
              <option value="manager">Manager</option>
            </select>
            <span className="form-help">{ROLE_DESCRIPTIONS[role]}</span>
          </div>

          <div className="agent-edit-field">
            <label>Model</label>
            <select value={model} onChange={(e) => setModel(e.target.value)} className="manage-select">
              {MODELS.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
            <span className="form-help">{MODELS.find((m) => m.value === model)?.desc}</span>
          </div>

          <div className="agent-edit-field">
            <label>System Prompt</label>
            <pre className="agent-prompt-preview">
              {(agent.config?.system_prompt as string) || `Default ${role} prompt (built-in)`}
            </pre>
          </div>

          <div className="agent-edit-field">
            <label>Agent ID</label>
            <code className="agent-id-display">{agent.id}</code>
          </div>

          {isDirty && (
            <div className="agent-edit-actions">
              <button
                className="manage-btn manage-btn-primary"
                onClick={handleSave}
                disabled={updateAgent.isPending}
              >
                {updateAgent.isPending ? "Saving..." : "Save Changes"}
              </button>
              <button
                className="manage-btn"
                onClick={() => {
                  setName(agent.name);
                  setModel(agent.model);
                  setRole(agent.role);
                }}
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Create Agent Form ─────────────────────────────────

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
      { name: name.trim(), role, model, config: {} },
      {
        onSuccess: () => {
          setName("");
          showToast("Agent added!", "success");
        },
      }
    );
  };

  return (
    <form className="manage-form agent-create-form" onSubmit={handleSubmit}>
      <input
        type="text"
        placeholder="Agent name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="manage-input"
      />
      <select value={role} onChange={(e) => setRole(e.target.value)} className="manage-select">
        <option value="engineer">Engineer</option>
        <option value="reviewer">Reviewer</option>
        <option value="manager">Manager</option>
      </select>
      <select value={model} onChange={(e) => setModel(e.target.value)} className="manage-select">
        {MODELS.map((m) => (
          <option key={m.value} value={m.value}>{m.label}</option>
        ))}
      </select>
      <button type="submit" className="manage-btn manage-btn-primary" disabled={createAgent.isPending || !name.trim()}>
        + Add
      </button>
    </form>
  );
}

// ─── Register Repo Form ────────────────────────────────

function RegisterRepoForm({ teamId }: { teamId: string }) {
  const [name, setName] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [validated, setValidated] = useState<{
    valid: boolean;
    default_branch: string | null;
    is_dirty: boolean;
    remote_url: string | null;
    error: string | null;
  } | null>(null);
  const validateRepo = useValidateRepo();
  const [branch, setBranch] = useState("main");
  const registerRepo = useRegisterRepo(teamId);
  const { showToast } = useToast();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !localPath.trim()) return;
    registerRepo.mutate(
      { name: name.trim(), local_path: localPath.trim(), default_branch: branch.trim() || "main" },
      {
        onSuccess: () => {
          setName("");
          setLocalPath("");
          setBranch("main");
          showToast("Repository registered!", "success");
        },
      }
    );
  };

  const handleValidate = () => {
    if (!localPath.trim()) return;
    validateRepo.mutate(
      { local_path: localPath.trim() },
      {
        onSuccess: (data) => {
          setValidated(data);
          if (data.valid && data.default_branch) {
            setBranch(data.default_branch);
          }
          if (data.valid && !name) {
            // Auto-fill name from path
            const parts = localPath.trim().split("/");
            setName(parts[parts.length - 1] || "");
          }
        },
      }
    );
  };

  return (
    <div>
      <form className="manage-form manage-repo-form" onSubmit={handleSubmit}>
        <input type="text" placeholder="Local path (e.g. /home/user/project)" value={localPath}
          onChange={(e) => { setLocalPath(e.target.value); setValidated(null); }}
          className="manage-input" />
        <button type="button" className="manage-btn manage-btn-secondary"
          onClick={handleValidate} disabled={validateRepo.isPending || !localPath.trim()}>
          {validateRepo.isPending ? "Checking..." : "Validate"}
        </button>
      </form>

      {validated && (
        <div className={`repo-validation ${validated.valid ? "valid" : "invalid"}`}>
          {validated.valid ? (
            <>
              <span className="repo-valid-badge">Valid git repo</span>
              <span className="repo-validation-detail">
                Branch: {validated.default_branch}
                {validated.is_dirty && " (dirty)"}
                {validated.remote_url && ` | ${validated.remote_url}`}
              </span>
            </>
          ) : (
            <span className="repo-invalid-msg">{validated.error}</span>
          )}
        </div>
      )}

      {validated?.valid && (
        <form className="manage-form manage-repo-form" onSubmit={handleSubmit}>
          <input type="text" placeholder="Repo name" value={name}
            onChange={(e) => setName(e.target.value)} className="manage-input" />
          <input type="text" placeholder="Default branch" value={branch}
            onChange={(e) => setBranch(e.target.value)} className="manage-input manage-input-sm" />
          <button type="submit" className="manage-btn manage-btn-primary"
            disabled={registerRepo.isPending || !name.trim()}>
            {registerRepo.isPending ? "Adding..." : "+ Register"}
          </button>
        </form>
      )}
    </div>
  );
}

// ─── Team Panel ────────────────────────────────────────

function TeamPanel({ teamId, teamName }: { teamId: string; teamName: string }) {
  const { data: agents } = useAgents(teamId);
  const { data: repos } = useRepos(teamId);
  const [showRepoForm, setShowRepoForm] = useState(false);

  return (
    <div className="manage-card">
      <div className="manage-card-header">
        <h3>{teamName}</h3>
        <div className="manage-badges">
          <span className="manage-badge">{agents?.length ?? 0} agents</span>
          <span className="manage-badge">{repos?.length ?? 0} repos</span>
        </div>
      </div>

      {/* Agents */}
      <h4 className="manage-subsection-title">Agents</h4>
      <p className="form-help">Click an agent to edit name, model, or role.</p>

      {agents && agents.length > 0 && (
        <div className="agent-manage-list">
          {agents.map((a) => (
            <AgentCard key={a.id} agent={a} teamId={teamId} />
          ))}
        </div>
      )}

      <CreateAgentForm teamId={teamId} />

      {/* Repositories */}
      <h4 className="manage-subsection-title" style={{ marginTop: "1.5rem" }}>Repositories</h4>

      {repos && repos.length > 0 && (
        <div className="manage-repo-list">
          {repos.map((r) => (
            <div key={r.id} className="manage-repo-row">
              <span className="manage-repo-name">{r.name}</span>
              <span className="manage-repo-path">{r.local_path}</span>
              <span className="manage-repo-branch">{r.default_branch}</span>
            </div>
          ))}
        </div>
      )}

      <button
        className="manage-btn manage-btn-secondary manage-btn-sm"
        onClick={() => setShowRepoForm(!showRepoForm)}
      >
        {showRepoForm ? "Cancel" : "+ Add Repository"}
      </button>
      {showRepoForm && <RegisterRepoForm teamId={teamId} />}
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────

export function Manage({ orgId }: { orgId: string; onOrgChange?: (id: string) => void }) {
  const { data: teams } = useTeams(orgId || undefined);

  return (
    <div className="manage-page">
      <h1>Manage</h1>

      {/* Teams */}
      <div className="manage-section">
        {teams && teams.length > 0 ? (
          <div className="manage-grid">
            {teams.map((t) => (
              <TeamPanel key={t.id} teamId={t.id} teamName={t.name} />
            ))}
          </div>
        ) : (
          <div className="manage-empty-state">
            <p className="manage-empty">No teams yet</p>
            <p className="form-help">Create a team to start adding agents.</p>
          </div>
        )}

        {orgId && (
          <div style={{ marginTop: "1.5rem" }}>
            <CreateTeamForm orgId={orgId} />
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Create Team Form ──────────────────────────────────

function CreateTeamForm({ orgId }: { orgId: string }) {
  const [name, setName] = useState("");
  const createTeam = useCreateTeam(orgId);
  const { showToast } = useToast();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    createTeam.mutate(
      { name: name.trim(), slug: toSlug(name) },
      { onSuccess: () => { setName(""); showToast("Team created!", "success"); } }
    );
  };

  return (
    <form className="manage-form" onSubmit={handleSubmit}>
      <input type="text" placeholder="New team name" value={name} onChange={(e) => setName(e.target.value)} className="manage-input" />
      <button type="submit" className="manage-btn manage-btn-primary" disabled={createTeam.isPending || !name.trim()}>
        + Create Team
      </button>
    </form>
  );
}
