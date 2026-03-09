#!/usr/bin/env python3
"""
Entourage Auto PR + Two-Tier Review Example.

Demonstrates the Tier 1 agent pipeline:
  1. Engineer agent finishes work
  2. Branch is pushed and a GitHub PR is auto-created
  3. Reviewer agent is auto-assigned for first-pass review
  4. Reviewer requests changes → engineer addresses feedback
  5. Reviewer approves → human gives final approval

Run with: python examples/auto_pr_and_review.py

Requires: pip install httpx
Backend must be running: http://localhost:8000

Note: Push and PR creation require a real git repo with a GitHub remote.
      This example demonstrates the full API flow — push/PR calls will
      return errors if no real repo exists, but the review flow still works.
"""

from _common import setup_workspace


def main():
    # ── Setup: engineer + reviewer agents ──────────────────────
    ws = setup_workspace(
        "PR Review Demo",
        engineers=[
            {"name": "eng-1", "role": "engineer", "description": "Backend engineer"},
            {"name": "reviewer-1", "role": "reviewer", "description": "Code reviewer"},
        ],
        repo={"name": "api-server"},
    )
    client = ws["client"]
    team = ws["team"]
    engineer = ws["engineers"][0]
    reviewer = ws["engineers"][1]
    repo = ws["repo"]

    print(f"\n  Engineer: {engineer['name']} (role={engineer['role']})")
    print(f"  Reviewer: {reviewer['name']} (role={reviewer['role']})")

    # ── Create and assign task ─────────────────────────────────
    task = client.post(f"/teams/{team['id']}/tasks", json={
        "title": "Add rate limiting middleware",
        "description": "Add 100 req/min rate limiting to all public API endpoints using Redis",
        "priority": "high",
        "task_type": "feature",
    }).json()

    client.post(f"/tasks/{task['id']}/assign", json={"assignee_id": engineer["id"]})
    client.post(f"/tasks/{task['id']}/status", json={"status": "in_progress"})

    print(f"\nTask #{task['id']}: {task['title']}")
    print(f"  Status:  in_progress")
    print(f"  Branch:  {task['branch']}")
    print(f"  Assigned: {engineer['name']}")

    # ── Phase 1: Push branch ───────────────────────────────────
    print("\n" + "═" * 60)
    print("PHASE 1: Push branch to remote")
    print("═" * 60)

    resp = client.post(
        f"/tasks/{task['id']}/push",
        params={"repo_id": repo["id"]},
    )
    if resp.status_code == 200:
        push = resp.json()
        print(f"\n  ✓ Branch pushed: {push['branch']}")
    else:
        print(f"\n  ⚠ Push skipped (no real repo): {resp.status_code}")
        print(f"    In production this pushes the task branch to origin.")

    # ── Phase 2: Create PR ─────────────────────────────────────
    print("\n" + "═" * 60)
    print("PHASE 2: Create GitHub PR")
    print("═" * 60)

    resp = client.post(f"/tasks/{task['id']}/pr", json={
        "repo_id": repo["id"],
        "title": f"feat: {task['title'].lower()}",
        "body": f"## Summary\nAdd rate limiting middleware.\n\nCloses #{task['id']}",
        "draft": False,
    })
    if resp.status_code == 200:
        pr = resp.json()
        print(f"\n  ✓ PR created: {pr.get('pr_url', 'N/A')}")
        print(f"    PR number:  #{pr.get('pr_number', 'N/A')}")
    else:
        print(f"\n  ⚠ PR creation skipped (no real repo): {resp.status_code}")
        print(f"    In production this creates a PR via `gh pr create`.")

    # ── Phase 3: Request review → auto-assign reviewer ─────────
    print("\n" + "═" * 60)
    print("PHASE 3: Request review (auto-assigns reviewer agent)")
    print("═" * 60)

    client.post(f"/tasks/{task['id']}/status", json={"status": "in_review"})

    resp = client.post(f"/tasks/{task['id']}/reviews", json={
        "reviewer_type": "agent",
    })
    review = resp.json()
    print(f"\n  Review #{review['id']} created")
    print(f"  Attempt: {review['attempt']}")
    print(f"  The system auto-assigns an idle reviewer-role agent.")
    print(f"  Reviewer agent reads the diff, adds comments, and gives a verdict.")

    # ── Phase 4: Reviewer agent adds comments ──────────────────
    print("\n" + "═" * 60)
    print("PHASE 4: Reviewer agent adds file-anchored comments")
    print("═" * 60)

    client.post(f"/reviews/{review['id']}/comments", json={
        "file_path": "middleware/rate_limiter.py",
        "line_number": 15,
        "body": "Fixed window counter allows 2x rate at window boundaries. "
                "Consider a sliding window algorithm.",
    })
    print(f"\n  Comment on rate_limiter.py:15")
    print(f"    'Fixed window → sliding window concern'")

    client.post(f"/reviews/{review['id']}/comments", json={
        "file_path": "middleware/rate_limiter.py",
        "line_number": 42,
        "body": "Add a TTL to the Redis key to prevent orphaned entries.",
    })
    print(f"\n  Comment on rate_limiter.py:42")
    print(f"    'Add TTL to Redis key'")

    # ── Phase 5: Reviewer requests changes ─────────────────────
    print("\n" + "═" * 60)
    print("PHASE 5: Reviewer agent verdict — request changes")
    print("═" * 60)

    client.post(f"/reviews/{review['id']}/verdict", json={
        "verdict": "request_changes",
        "summary": "Two issues:\n"
                   "1. Switch to sliding window algorithm\n"
                   "2. Add Redis TTL to rate limit keys",
    })
    print(f"\n  Verdict: request_changes")
    print(f"  → Task auto-dispatched back to engineer with feedback.")
    print(f"  → Engineer receives review comments via MCP tools.")

    # ── Phase 6: Engineer addresses feedback, re-requests review ─
    print("\n" + "═" * 60)
    print("PHASE 6: Engineer addresses feedback")
    print("═" * 60)

    print("\n  (Engineer reads comments via get_review_comments MCP tool...)")
    print("  (Engineer fixes sliding window + adds TTL...)")
    print("  (Engineer pushes updated branch...)")

    # Task was moved back to in_progress by request_changes feedback loop.
    # Transition back to in_review for the next round.
    client.post(f"/tasks/{task['id']}/status", json={"status": "in_review"})

    resp = client.post(f"/tasks/{task['id']}/reviews", json={
        "reviewer_type": "agent",
    })
    review2 = resp.json()
    print(f"\n  New review round: #{review2['id']} (attempt {review2['attempt']})")

    # ── Phase 7: Reviewer approves (agent tier) ────────────────
    print("\n" + "═" * 60)
    print("PHASE 7: Reviewer agent approves (first tier)")
    print("═" * 60)

    client.post(f"/reviews/{review2['id']}/verdict", json={
        "verdict": "approve",
        "summary": "Sliding window is correct. TTL is in place. Ship it.",
    })
    print(f"\n  Agent verdict: approve ✓")
    print(f"  → Task stays in 'in_review' for human approval (two-tier).")
    print(f"  → Agent approval ≠ final approval. Human reviews next.")

    # ── Phase 8: Human gives final approval ────────────────────
    print("\n" + "═" * 60)
    print("PHASE 8: Human approves (second tier) → merge → done")
    print("═" * 60)

    for status in ["in_approval", "merging", "done"]:
        client.post(f"/tasks/{task['id']}/status", json={"status": status})
    final = client.get(f"/tasks/{task['id']}").json()
    print(f"\n  Task #{final['id']}: {final['status']}")

    # ── Event trail ────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("Complete audit trail:")
    print("═" * 60)
    events = client.get(f"/tasks/{task['id']}/events").json()
    for i, event in enumerate(events, 1):
        print(f"  {i}. [{event['type']}]")

    print(f"\n✓ Auto-PR + two-tier review complete.")
    print(f"  Push → PR → agent review → human approval → merged.")
    print(f"  {len(events)} events in the audit trail.")


if __name__ == "__main__":
    main()
