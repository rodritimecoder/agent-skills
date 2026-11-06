# Skill distribution: GitHub canonical, harnesses derived

> **Status: implemented** (2026-10-21) on the Linux workstation. This document
> describes the model as built, not as proposed. It supersedes the earlier
> worktree-per-harness plan: OpenCode V2 can read a path directly, so the
> zero-copy pointer is used where the harness supports it and rsync remains
> only where it does not.

---

## The model

There is one source of truth and one kind of derivative.

```
                  github.com/rodritimecoder/my-agent-skills
                                    │  git push / git pull
                   ┌────────────────┴────────────────┐
                   ▼                                 ▼
      Linux: ~/src/my-agent-skills        Mac: ~/src/my-agent-skills
                   │                                 │
        ┌──────────┼──────────┐           ┌──────────┴─────────┐
        ▼          ▼          ▼           ▼                    ▼
   gemini/agy      pi      opencode   gemini/agy            opencode
   rsync copy  rsync copy   pointer   rsync copy            pointer
```

- **Edit** in the checkout. **Push** to GitHub. **Pull** on the other machine.
- A harness is never a source. `sync-skills --pull` is retired; it only ever
  read one harness, so an edit made in pi or opencode was destroyed by the next
  `rsync --delete` with no warning.

On Linux, `/run/media/rodri/AI/skills` is a symlink to the same checkout, so
the ~70 absolute `/run/media/rodri/AI/skills/…` references in older docs and
scripts keep resolving. The AI volume keeps what justifies a removable volume:
`models/`, `sh/`, `llama.cpp/`.

---

## Two mechanisms

| Harness | Mechanism | Why |
| :--- | :--- | :--- |
| `~/.gemini/config/skills` | `rsync -aL --delete` from the checkout | it has always been given a flat, dereferenced tree; keeping the copy keeps the proven behaviour |
| `~/.gemini/antigravity-cli/skills` | same | same |
| `~/.pi/agent/skills` | same | same |
| `~/.config/opencode/skills` | **removed**; `opencode.json` points at `<checkout>/surface` | OpenCode V2 supports `"skills": ["<path>"]`, so no copy exists to drift |

`sync-skills` decides which is which; no harness has its own content tree.

---

## Why `surface/` exists

`sync-skills` generates `surface/`: one relative symlink per skill, nothing
else. It is the only path a harness should be pointed at.

Measured, not assumed. Pointing OpenCode at the repository root discovers
everything at depth ≤ 6, including things that are not skills:

| Scan target | Skills seen | What leaks |
| :--- | ---: | :--- |
| repository root, before `archived/` was disarmed | 48 | 6 retired skills + `AGENTS` + `README` |
| repository root, after disarming 5 of 6 | 43 | `AGENTS`, `README`, `omnicli` |
| `surface/` | **38** | nothing (`omnicli` is not on it) |

`AGENTS` and `README` appear because a source directory's *own* `*.md` files
count as skills. A generated surface is the only layout that is correct by
construction rather than by exclusion list.

The `archived/` leak is why retired skills are disarmed by renaming
`SKILL.md` → `SKILL.md.disabled`: the content stays in the repository, and no
harness discovers it.

`orchestration/omnicli` is a normal published skill as of 2026-10-30: it
appears in the surface, so a harness discovers it in shelf mode, and the
bundle manifest lists it. Gateway mode still fetches it explicitly when a
harness should see only the gateway.

---

## Bootstrap a machine

Linux (done) and macOS use the same command:

```bash
github-architect bootstrap
```

It clones `my-agent-skills` to `~/src/my-agent-skills` (override with
`SKILLS_CANONICAL`), links `sync-skills` and `github-architect` into
`~/.local/bin`, and runs the sync, which builds `surface/`, writes
`~/.config/opencode/opencode.json`, and refreshes whichever harness directories
exist on that machine.

Manual equivalent:

```bash
gh repo clone rodritimecoder/my-agent-skills ~/src/my-agent-skills
~/src/my-agent-skills/sync_skills.sh --push
```

No macOS-specific step: `sync_skills.sh` avoids `readlink -f`, and the surface
links are relative so the checkout can move.

---

## Verify

```bash
sync-skills verify                    # surface, OpenCode pointer, harness copies
python3 ~/src/my-agent-skills/ports.py check
```

For OpenCode specifically, the live discovery list is available from the
server — this is the end-to-end proof, not a claim:

```bash
opencode api GET /api/skill | jq -r '.data[].path'
```

Expected: 2 built-in skills (`opencode`, `report`) plus 38 paths under
`~/src/my-agent-skills/surface/`, no duplicate IDs, no `archived/` entry.

`verify` is deliberately read-only: it does not rebuild the surface first, so it
can report a stale one. It fails on a dangling surface link, a retired skill on
the surface, a stale skill in a harness copy, a skill missing from a harness
copy, or an OpenCode config that does not list the surface.

---

## Retiring a skill

1. Move the directory to `archived/<name>/` (or leave it and stop linking it).
2. Rename its entry point: `git mv SKILL.md SKILL.md.disabled`.
3. `sync-skills --push`.

Step 2 is the one that matters. Without it the skill is discoverable again the
moment anything scans the repository root or the surface is rebuilt from a
stale root link.

---

## Rollback

- **Harness content**: `~/.config/opencode/skills.rsync-backup` holds the last
  copied OpenCode harness. Restore it and delete the `skills` key from
  `opencode.json`.
- **Legacy path**: `/run/media/rodri/AI/skills.pre-ext4` is the pre-move copy of
  the checkout. `rm /run/media/rodri/AI/skills` then `mv
  /run/media/rodri/AI/skills.pre-ext4 /run/media/rodri/AI/skills` restores the
  previous layout exactly.
- **Content**: `git revert` the distribution commit.

---

## Resolved: `:8089` manifest gap

`imajev-decider.sh` bound `:8089` while `ports.json` listed the port as retired,
so `ports.py check` failed and every `sync-skills` needed `SKIP_PORTS_CHECK=1`.
`:8089` is now the `decision-fallback` slot (Imajev-4B), so `check` is clean and
no override is required. If the launcher is ever archived again, retire the slot
in the same commit — a live launcher and a `retired` entry cannot coexist.
