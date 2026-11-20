# T3 Code PR & Worktree Workflow

> **Scope gate:** Follow this guide **only when running inside T3 Code** (when `link_pull_request`, `watch_pull_request`, `delegate_task`, or `t3_worktree_handoff` tools are present). Outside T3 Code, ignore this file and use `git-sync` + the `gh` CLI directly.

---

## Tool boundary: `git-sync` vs. T3 Code

T3 Code does not replace `git-sync` or `github-architect` for repository hygiene. Keep each layer in its lane:

| Job | Canonical tool |
| :--- | :--- |
| Secret/blob guard, explicit staging, commit message gate, `--no-rebase` pull, protected-branch push | `git-sync` / `git-sync guarded-commit` |
| Repo audit, scaffold, private publish, clone, fleet sync (`status-all`, `sync-all`), workstation bootstrap | `github-architect` |
| Isolated child checkouts, thread worktree handoff | `delegate_task` (`isolation: "worktree"`), `t3_worktree_handoff`, `t3_thread_launch` |
| Pinning PRs to a thread and settling on merge | `link_pull_request`, `link_pull_requests`, `list_thread_pull_requests`, `unlink_pull_request` |
| Waiting on CI checks, reviews, or merge conflicts | `watch_pull_request`, `unwatch_pull_request` |

---

## 1. Worktree-to-PR handoff

1. **Isolate branch work with T3 tools, never shell `git worktree`:**
   - **Child builder with its own PR/checkout:** call `delegate_task` with `isolation: "worktree"` (branches from the parent commit; uncommitted parent edits stay out). Never create a child's checkout inside the shell or inside `task`.
   - **Move the current thread onto a new worktree branch:** call `t3_worktree_status` first, then `t3_worktree_handoff` as the last call in your turn (ends the live session; pass `continuationPrompt` to resume automatically).
   - **User-requested new top-level worktree thread:** call `t3_thread_launch` with `workspaceStrategy` (`type: "worktree"`).
2. **Commit and push inside the worktree using `git-sync`:**
   - Stage and commit with `git-sync` (or `git-sync guarded-commit` + `git-sync -y`) so `publication_guard` and the commit-body standard run before anything hits GitHub.
   - Open the PR with `gh pr create` (or `pull_request_create` if the host exposes `pull_request_*` tools).
3. **Child handoff line:** after PR work, a child ends with:
   `PR <full URL>, head <SHA>, checks and reviews <state>`.

---

## 2. PR creation, linking, and reactive watching

1. **Link every PR you create, take over, or push to:**
   - Immediately call `link_pull_request` (pass full `url`, or `repository` + `number`) or `link_pull_requests` (for multiple/stacked PRs). T3 displays live PR status beside the thread and settles the thread on merge.
   - Skip PRs you only read/review or mention as background.
   - Use `list_thread_pull_requests` to inspect linked PRs and stack order (bottom to top), and `unlink_pull_request` / `unlink_pull_requests` to drop stale links.
2. **Watch reactively instead of polling:**
   - When asked to monitor/babysit a PR, or when work you were asked to do (such as merging) waits on checks or reviews: finish any branch updates and pushes first, handle existing comments first, then call `watch_pull_request`:
     - `until: "checks"` — wake when checks finish, for a PR you are handing back to the user (default for new watches).
     - `until: "merged"` — keep watching until merged, closed, or unwatched, when you will act on it yourself (such as merging after approval).
   - After `watch_pull_request`, **end your turn**. Never poll with `sleep`, `gh pr checks --watch`, loops, or timers.
   - On a wake, do **not** call `watch_pull_request` again — the watch stays active across wakes and pushes. A wake is not a merge decision; inspect readiness before acting.
3. **Unwatch before handback:**
   - Call `unwatch_pull_request` on any PR you are watching before handing control back to the user (the PR remains linked to the thread).
4. **Host PR tool preference:**
   - If the host exposes `pull_request_*`, `ci_logs`, or `ci_rerun` tools, use them instead of `gh` for PR/CI operations. Otherwise use `gh` for PR creation/merging/CI logs and T3 MCP tools for linking and watching.
