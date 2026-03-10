# Webhook Automation

Instead of manually creating tasks when GitHub issues come in, let Entourage listen for webhooks and auto-create work for your agents. This guide shows how to wire up GitHub → Entourage.

## How it works

```
GitHub issue created
        ↓
POST /webhooks/{id}/receive
        ↓
Verify HMAC-SHA256 signature
        ↓
Log delivery in webhook_deliveries
        ↓
Process event → auto-create task
        ↓
Map GitHub labels → task priority
        ↓
(optional) Auto-assign to idle agent
        ↓
PG NOTIFY → Dispatcher → Agent starts work
```

Every webhook delivery is logged. You can see what came in, whether it was processed, and what action was taken.

## Authentication

All Entourage API endpoints require authentication, including webhook management. You can authenticate using either method:

### API key

```bash
curl -X GET http://localhost:8000/api/v1/webhooks \
  -H "X-API-Key: oc_your_key_here"
```

### JWT bearer token

```bash
curl -X GET http://localhost:8000/api/v1/webhooks \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

Use whichever method fits your setup. API keys are better for server-to-server integrations; JWT tokens are better for user-facing flows.

## Step 1: Register a webhook

```bash
curl -X POST http://localhost:8000/api/v1/webhooks \
  -H "Content-Type: application/json" \
  -H "X-API-Key: oc_your_key_here" \
  -d '{
    "org_id": "{org_id}",
    "team_id": "{team_id}",
    "name": "GitHub Issues + PRs",
    "provider": "github",
    "events": ["issues", "pull_request"],
    "config": {
      "auto_assign": true
    }
  }'
```

The `team_id` is required for auto-task creation. Without it, events are logged but no tasks are created. The `auto_assign` config option assigns new tasks to the first idle agent in the team.

Response:

```json
{
  "id": "webhook-uuid",
  "secret": "whsec_abc123...",
  "events": ["issues.opened", "issues.closed", "pull_request.opened", "pull_request.merged"],
  "active": true
}
```

Save the `secret` — you'll need it when configuring GitHub.

## Step 2: Configure GitHub

In your GitHub repo: **Settings → Webhooks → Add webhook**

| Field | Value |
|-------|-------|
| Payload URL | `https://your-server.com/api/v1/webhooks/{webhook_id}/receive` |
| Content type | `application/json` |
| Secret | The `secret` from Step 1 |
| Events | Select "Issues" and "Pull requests" |

For local development, use a tunnel like [ngrok](https://ngrok.com):

```bash
ngrok http 8000
# Use the ngrok URL as your Payload URL
```

## Step 3: Verify it works

Create a GitHub issue. Entourage receives the webhook, verifies the HMAC signature, and processes it.

Check deliveries:

```bash
curl http://localhost:8000/api/v1/webhooks/{webhook_id}/deliveries \
  -H "X-API-Key: oc_your_key_here"
```

```json
[
  {
    "id": "delivery-uuid",
    "event_type": "issues.opened",
    "status": "processed",
    "payload_summary": {"action": "opened", "issue": {"title": "Login broken on Safari"}},
    "created_at": "2026-02-27T..."
  }
]
```

## What happens for each event

### `issues.opened` → Task created

When someone opens a GitHub issue, Entourage auto-creates a task:

```
GitHub Issue #42: "Login broken on Safari"
  Labels: ["critical", "auth"]
  ↓
Entourage Task:
  title: "[GitHub] Login broken on Safari"
  description: "GitHub Issue #42\n\n<issue body>"
  priority: critical    ← mapped from "critical" label
  status: todo
  tags: ["github", "issue", "critical", "auth"]
```

**Label → Priority mapping:**

| GitHub labels | Entourage priority |
|--------------|-------------------|
| `critical`, `urgent`, `P0` | `critical` |
| `high`, `important`, `P1` | `high` |
| `low`, `minor`, `P3` | `low` |
| _(anything else)_ | `medium` |

If `auto_assign` is enabled in webhook config, the task gets assigned to the team's first idle agent and dispatch starts immediately.

### `pull_request.opened` → Task created

A new PR auto-creates a task:

```
GitHub PR #99: "Add rate limiting"
  ↓
Entourage Task:
  title: "[GitHub PR] Add rate limiting"
  description: "GitHub PR #99\n\n<PR body>"
  priority: medium
  tags: ["github", "pull_request"]
```

### Other events

Events like `push`, `issues.closed`, `pull_request.merged` are logged in the delivery audit trail but do not currently create or modify tasks.

## Security: HMAC-SHA256 verification

Every incoming webhook is verified using HMAC-SHA256:

```
Expected signature = HMAC-SHA256(webhook_secret, raw_request_body)
Actual signature   = X-Hub-Signature-256 header from GitHub
```

If they don't match, the request is rejected with 401. This prevents:
- Spoofed webhook calls
- Replay attacks
- Tampered payloads

### HMAC signature verification pattern

If you are building a custom integration that sends webhooks to Entourage, here is how to compute the signature:

```python
import hmac
import hashlib

def compute_signature(secret: str, payload: bytes) -> str:
    """Compute HMAC-SHA256 signature for webhook payload."""
    mac = hmac.new(
        secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    )
    return f"sha256={mac.hexdigest()}"

# When sending a webhook to Entourage:
signature = compute_signature("whsec_abc123...", request_body)
headers = {
    "X-Hub-Signature-256": signature,
    "Content-Type": "application/json",
}
```

Entourage uses constant-time comparison (`hmac.compare_digest`) to prevent timing attacks.

### Authenticated webhook delivery

When Entourage delivers outbound webhook notifications (e.g., task status changes to an external system), it includes authentication headers so the receiving system can verify the request came from Entourage:

```
POST https://your-system.com/entourage-webhook
Content-Type: application/json
X-API-Key: oc_your_key_here
X-Entourage-Signature: sha256=a1b2c3d4...
X-Entourage-Event: task.completed
X-Entourage-Delivery: delivery-uuid

{
  "event": "task.completed",
  "task_id": 601,
  "team_id": "team-uuid",
  "timestamp": "2026-02-27T14:30:00Z"
}
```

The receiving system should:
1. Verify the `X-Entourage-Signature` header using the shared secret
2. Optionally verify the `X-API-Key` matches a known key
3. Process the event and return `200 OK`

## Filtering events

You don't have to process everything. The `events` array controls what gets processed:

```bash
# Only listen for new issues
curl -X PATCH http://localhost:8000/api/v1/webhooks/{webhook_id} \
  -H "Content-Type: application/json" \
  -H "X-API-Key: oc_your_key_here" \
  -d '{"events": ["issues.opened"]}'
```

Events not in the list are still logged (for audit) but not processed.

## Monitoring webhooks

### Check webhook status

```bash
curl http://localhost:8000/api/v1/webhooks/{webhook_id} \
  -H "X-API-Key: oc_your_key_here"
```

### List all deliveries

```bash
curl http://localhost:8000/api/v1/webhooks/{webhook_id}/deliveries \
  -H "X-API-Key: oc_your_key_here"
```

Shows every delivery with status (`received`, `processed`, `failed`), timestamps, and payload summaries.

### Regenerate secret

If your webhook secret is compromised:

```bash
curl -X POST http://localhost:8000/api/v1/webhooks/{webhook_id}/regenerate-secret \
  -H "X-API-Key: oc_your_key_here"
```

Update the new secret in GitHub settings.

## Example: Full GitHub → Entourage run

```
1. Developer opens GitHub issue: "Add dark mode support"
2. GitHub sends webhook → Entourage
3. Entourage creates Task: "Add dark mode support" (status: todo)
4. Manager agent decomposes into sub-tasks:
   - "Add theme context provider" → eng-frontend
   - "Create dark color palette" → eng-frontend
   - "Add toggle to settings page" → eng-frontend (depends on above)
5. Engineers work through MCP tools
6. Each sub-task goes through code review
7. After all sub-tasks merge → parent task closes
8. Entourage can update the GitHub issue: "Resolved in tasks #601-#603"
```

The entire flow from issue to deployed fix is tracked, reviewed, and auditable.
