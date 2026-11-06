# Script-to-Animation

This workspace guides you from a content idea through script writing, animation specification, and build -- one stage at a time.

## Not this workspace

| If | Go to instead |
|---|---|
| the video needs recorded narration as the timing source | `voice-driven-animation` |
| you already have a finished spec and only need code | enter at `stages/03-build/CONTEXT.md` |
| the deliverable is on-camera footage or live action | neither — this is an animation-only pipeline |
| the whole job fits in one prompt | no workspace; just do it (see the ladder guardrail in the skill) |

Say which one and hand off, rather than starting `01-script` on the wrong work.

## Folder Map

```
script-to-animation/
├── AGENTS.md              (you are here)
├── CONTEXT.md             (start here for task routing)
├── setup/
│   └── questionnaire.md   (onboarding -- run with "setup")
├── skills/                (bundled Claude skills for build and design)
│   ├── remotion-best-practices/  (full Remotion skill: SKILL.md + 35 rule files)
│   └── frontend-design/   (design philosophy and aesthetics: SKILL.md)
├── brand-vault/
│   ├── CONTEXT.md         (routes to voice and identity files)
│   ├── voice-rules.md     (writing voice and tone)
│   └── identity.md        (brand name, audience, positioning)
├── stages/
│   ├── 01-script/         (topic -> finished script)
│   │   ├── CONTEXT.md
│   │   ├── output/
│   │   └── references/    (hook system, templates, pillars)
│   ├── 02-spec/           (script -> animation spec)
│   │   ├── CONTEXT.md
│   │   ├── output/
│   │   └── references/    (spec format, components, design system)
│   └── 03-build/          (spec -> Remotion code)
│       ├── CONTEXT.md
│       ├── output/
│       └── references/    (build conventions)
└── shared/
    └── platform-specs.md  (resolution, duration, format per platform)
```

## Triggers

| Keyword | Action |
|---------|--------|
| `setup` | Run onboarding questionnaire -- configures brand, voice, audience, platform |
| `status` | Show pipeline completion for all three stages |

### How `status` works

Scan `stages/*/output/` folders and compare modification times. A stage is:

| State | When |
|---|---|
| `PENDING` | no files in `output/` (ignoring `.gitkeep`) |
| `COMPLETE` | has files, and its newest file is newer than the previous stage's newest file |
| `STALE` | has files, but its newest file is **older** than the previous stage's newest file |

`STALE` means an upstream output was hand-edited after this stage ran, so this result no longer reflects its input. A presence-only check reports it as COMPLETE and hides the problem. Render:

```
Pipeline Status: script-to-animation

  [01-script]  ------>  [02-spec]  ------>  [03-build]
    COMPLETE           STALE              PENDING
```

When reporting a `STALE` stage, name the upstream file and date that caused it, then re-run that stage and every stage after it.

## Routing

| Task | Go To |
|------|-------|
| Write a script | `stages/01-script/CONTEXT.md` |
| Create an animation spec | `stages/02-spec/CONTEXT.md` |
| Build Remotion code | `stages/03-build/CONTEXT.md` |
| Configure this workspace | `setup/questionnaire.md` |

## What to Load

| Task | Load These | Do NOT Load |
|------|-----------|-------------|
| Write a script | `brand-vault/voice-rules.md`, `brand-vault/identity.md`, `stages/01-script/references/*`, `shared/platform-specs.md` | `skills/remotion-best-practices/`, `stages/02-spec/references/`, `stages/03-build/references/` |
| Create animation spec | `stages/01-script/output/`, `stages/02-spec/references/*`, `skills/frontend-design/SKILL.md` | `brand-vault/`, `stages/01-script/references/`, `stages/03-build/references/`, `skills/remotion-best-practices/` |
| Build Remotion code | `stages/02-spec/output/`, `stages/03-build/references/*`, `skills/remotion-best-practices/SKILL.md`, `stages/02-spec/references/design-system.md` | `brand-vault/`, `stages/01-script/`, `stages/02-spec/references/spec-format.md`, `stages/02-spec/references/animation-guide.md` |

## Stage Handoffs

Each stage writes its output to its own `output/` folder. The next stage reads from there. If you edit an output file between stages, the next stage picks up your edits. This is the primary way to steer the pipeline. The edited stage's downstream stages then report `STALE` until re-run.

## Re-running

Do not clear `output/` folders to start over — that destroys the handoff record. Either:

- **Re-run one stage:** overwrite that stage's `output/`. Downstream stages go `STALE` and you re-run them in order.
- **Start a new topic:** write new files into the same stage folders carrying a topic marker (`<topic>-script.md`), say in your report which files are current, and delete the superseded ones only once the new run is accepted.
