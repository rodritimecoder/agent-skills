# Workspace Builder

This workspace guides you through building a new MWP workspace for any domain -- from understanding the workflow through generating a complete, validated workspace scaffold.

## Not this workspace

| If | Go to instead |
|---|---|
| the folder already exists and needs auditing/restructuring | Restructure mode in the skill, not this pipeline |
| the work happens once, not repeatedly | no workspace; just do it (see the ladder guardrail) |
| you want to know what a change would hit, not build anything | the System map form (`references/system-map.md`) |
| you are validating an existing workspace rather than building one | enter at `stages/05-validation/CONTEXT.md` |

## Folder Map

```
workspace-builder/
├── AGENTS.md              (you are here)
├── CONTEXT.md             (start here for task routing)
├── setup/
│   └── questionnaire.md   (onboarding -- asks about the domain you are building for)
├── stages/
│   ├── 01-discovery/      (understand the domain workflow)
│   ├── 02-mapping/        (formalize stage contracts and dependencies)
│   ├── 03-scaffolding/    (generate the folder tree and files)
│   ├── 04-questionnaire-design/  (build the onboarding questionnaire)
│   └── 05-validation/     (verify against MWP conventions)
└── references/
    ├── conventions-reference.md   (pointer to core MWP conventions)
    └── examples/
        └── script-to-animation-summary.md  (completed workspace example)
```

## Triggers

| Keyword | Action |
|---------|--------|
| `setup` | Run onboarding -- asks about the domain you want to build a workspace for |
| `status` | Show pipeline completion for all five stages |

### How `status` works

Scan `stages/*/output/` folders and compare modification times. A stage is `PENDING` with no files (ignoring `.gitkeep`), `COMPLETE` when its newest file is newer than the previous stage's newest file, and `STALE` when its newest file is **older** than the previous stage's — an upstream output was edited after this stage ran. Render:

```
Pipeline Status: workspace-builder

  [01-discovery]  -->  [02-mapping]  -->  [03-scaffolding]  -->  [04-questionnaire]  -->  [05-validation]
      COMPLETE          COMPLETE           STALE                 PENDING                PENDING
```

This pipeline is especially prone to `STALE`: stages 03 and 04 emit files that stage 05 reads, so validating a scaffold you have since edited gives a false pass. Re-run 05 after any change to 03 or 04.

## Routing

| Task | Go To |
|------|-------|
| Start building a new workspace | `stages/01-discovery/CONTEXT.md` |
| Formalize stage contracts | `stages/02-mapping/CONTEXT.md` |
| Generate the workspace files | `stages/03-scaffolding/CONTEXT.md` |
| Design the onboarding questionnaire | `stages/04-questionnaire-design/CONTEXT.md` |
| Validate the workspace | `stages/05-validation/CONTEXT.md` |

## What to Load

| Task | Load These | Do NOT Load |
|------|-----------|-------------|
| Discover workflow | `references/conventions-reference.md`, `references/examples/script-to-animation-summary.md` | `stages/02-mapping/` through `stages/05-validation/` |
| Formalize contracts | `stages/01-discovery/output/`, `references/conventions-reference.md` | `references/examples/`, `stages/03-scaffolding/` through `stages/05-validation/` |
| Generate scaffold | `stages/02-mapping/output/`, `references/conventions-reference.md`, `/_core/templates/*`, `/_core/placeholder-syntax.md` | `stages/01-discovery/`, `references/examples/` |
| Design questionnaire | `stages/01-discovery/output/`, scaffolded workspace from stage 03, `/_core/templates/questionnaire-template.md` | `stages/02-mapping/`, `references/examples/` |
| Validate workspace | Scaffolded workspace from stage 03, `stages/04-questionnaire-design/output/`, `/_core/CONVENTIONS.md` | `stages/01-discovery/`, `stages/02-mapping/`, `references/examples/` |

## Stage Handoffs

Each stage writes its output to its own `output/` folder. The next stage reads from there. If you edit an output file between stages, the next stage picks up your edits.

The typical flow is sequential (01 through 05), but stage 05-validation also reads from stages 03 and 04 directly.

## Re-running

Never clear `output/` folders to start a new build — the previous scaffold is the comparison baseline and deleting it removes your ability to diff. Write the new build into a dated subfolder (`output/2026-03-30/`), keep both, and delete the old one only after the new one passes stage 05. If you must remove files, check for referrers first: `references/reference-integrity.md` in the skill covers the search.
