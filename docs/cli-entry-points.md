# CLI Entry Points

Three distribution layers, one source of truth.

```
/run/media/rodri/AI/skills/          the hub — every skill lives here
        │
        ├──→ ~/.pi/agent/skills/         Pi harness      (copy)
        ├──→ ~/.gemini/config/skills/    Gemini harness  (copy)
        ├──→ ~/.config/opencode/skills/  OpenCode harness (copy)
        │
        └──→ ~/.local/bin/<command>       the command layer (symlink)
```

The first three are copies the sync rewrites wholesale. The fourth is the
layer an agent actually types.

## Why it is a manifest now

`~/.local/bin` used to be hand-made. Archiving a skill or renaming a script
left a dead symlink behind, and nothing reported it — `sync-skills` would
print "✅ All skills synchronized" with three commands on PATH pointing at
files that had moved to `skills/archived/`.

`cli-manifest.json` in the hub declares every command the sync owns:

```json
{
  "commands": {
    "canvas-cli": {
      "target": "academic/canvas-cli/scripts/canvas_cli.py",
      "type": "script",
      "skill": "canvas-cli",
      "description": "Read Canvas LMS data: courses, assignments, submissions..."
    }
  }
}
```

`target` is relative to the hub, so a command always points at the canonical
copy — never at a satellite, which is derived and can be reaped.

On every sync the installer:

- creates the symlink if it is missing
- repairs it if it points somewhere else
- **withdraws** it if the declared target no longer exists, so a dead command
  disappears instead of lingering
- removes commands that left the manifest, tracked in
  `~/.config/agent-cli-commands.json`
- **never touches** a file it does not own: a hand-written shim of the same
  name is left alone, and external tools (`hf`, `yt-dlp`, `agent-reach`) are
  outside the manifest entirely

Set `AGENT_CLI_BIN` to install somewhere other than `~/.local/bin`.

## Adding a command

1. Add the entry to `cli-manifest.json` in the hub:

   ```json
   "my-tool": {
     "target": "hardware/my-tool/scripts/my_tool.py",
     "type": "script",
     "skill": "my-tool",
     "description": "One line on what it does."
   }
   ```

2. `sync-skills --push`

3. Verify: `command -v my-tool && my-tool --help`

The `target` path is relative to the hub. For a skill published to a
satellite bundle, point at the hub path, not the satellite path — the
satellite is generated and may be reaped, which would break the command the
same way an archived skill used to.

## What it is not

`cli-manifest.json` is not a package manifest. It declares *entry points on
this machine*, and it is deliberately not published to the public satellite
repositories: a public repo should not enumerate the private tools of one
workstation. The manifest lives in the hub, which is private.
