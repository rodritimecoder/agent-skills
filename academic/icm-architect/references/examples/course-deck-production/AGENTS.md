# Course Deck Production

A production system for turning unstructured source material (PDFs, papers, notes, scripts) into polished PowerPoint slide decks. Run `setup` once to configure your identity and design. Then start a new course anytime -- just provide source material and a topic.

This workspace guides you from raw source material to finished PowerPoint decks -- one stage at a time.

## Not this workspace

| If | Go to instead |
|---|---|
| the deliverable is narration, a video, or a script -- not slides | another workspace; this one ends in `.pptx` |
| you have the deck and need it edited, not generated | enter at `stages/04-generation/CONTEXT.md` |
| you only need the curriculum, no slides | stop after `stages/02-curriculum/CONTEXT.md` |
| the material is a single short brief, not a course | a saved prompt is probably enough (ladder guardrail) |

## Folder Map

```
course-deck-production/
├── AGENTS.md              (you are here)
├── CONTEXT.md             (start here for task routing)
├── setup/
│   └── questionnaire.md   (one-time onboarding -- identity and design)
├── skills/                (bundled Claude skills for generation and design)
│   ├── pptx/              (full pptx skill: SKILL.md, html2pptx.md, ooxml.md, scripts/)
│   └── frontend-design/   (design philosophy and aesthetics: SKILL.md)
├── design-system/         (colors and typography for your brand)
│   ├── CONTEXT.md
│   ├── palette.md
│   └── typography.md
├── shared/
│   ├── producer-identity.md  (who you are -- set during setup)
│   └── course-meta.md        (template for per-course metadata)
├── stages/
│   ├── 01-extraction/     (source material to structured content)
│   ├── 02-curriculum/     (structured content to course plan)
│   ├── 03-outline/        (course plan to slide-by-slide outlines)
│   ├── 04-generation/     (outlines to .pptx via html2pptx)
│   └── 05-qa-delivery/    (visual QA, fix, deliver)
```

## Triggers

| Keyword | Action |
|---------|--------|
| `setup` | Run one-time onboarding -- configures identity, design system, default workflow |
| `status` | Show pipeline completion for all five stages |

### How `status` works

Scan `stages/*/output/` folders and compare modification times. A stage is `PENDING` with no files (ignoring `.gitkeep`), `COMPLETE` when its newest file is newer than the previous stage's newest file, and `STALE` when its newest file is **older** than the previous stage's — an upstream output was edited after this stage ran. Render:

```
Pipeline Status: course-deck-production

  [01-extraction]  -->  [02-curriculum]  -->  [03-outline]  -->  [04-generation]  -->  [05-qa-delivery]
      COMPLETE           COMPLETE              STALE             PENDING            PENDING
```

Because a course runs through all five stages with the same filenames across runs, `STALE` is what tells you a `.pptx` was generated from an outline you have since changed. A presence check reports `COMPLETE` and ships the wrong deck. When reporting one, name the upstream file and date, then re-run that stage forward.

## Starting a New Course

Each course is a new run through the pipeline. Provide source material and a topic. The agent collects course details (name, audience, session count) conversationally at the start of whichever stage you enter, and writes a `[course-slug]-meta.md` to that stage's output. This metadata travels forward through the pipeline.

Your default starting stage is set during setup (see `shared/producer-identity.md`). You can always override per course.

To start a fresh run, **do not clear the output folders** -- that destroys the previous course and the handoff record, and nothing in the tree tells you what pointed at those files. Write the new course's files alongside the old ones with a course marker (`[course-slug]-meta.md`, `outline.md` under a dated subfolder), state in your report which files are current, and remove the superseded set only once the new course is delivered. If you must remove files, check referrers first: the skill's `references/reference-integrity.md` covers the search, including external ones (deploy scripts, cron) that no walk test can see.

## Routing

| Task | Go To |
|------|-------|
| Extract content from source material | `stages/01-extraction/CONTEXT.md` |
| Design the course curriculum | `stages/02-curriculum/CONTEXT.md` |
| Create slide outlines for sessions | `stages/03-outline/CONTEXT.md` |
| Generate PowerPoint decks | `stages/04-generation/CONTEXT.md` |
| Run visual QA and deliver | `stages/05-qa-delivery/CONTEXT.md` |

## What to Load

| Task | Load These | Do NOT Load |
|------|-----------|-------------|
| Extract content | `stages/01-extraction/references/*`, `shared/producer-identity.md`, `shared/course-meta.md` | `design-system/`, `skills/pptx/`, `stages/03-outline/` through `stages/05-qa-delivery/` |
| Design curriculum | `stages/01-extraction/output/`, `stages/02-curriculum/references/*` | `design-system/`, `skills/pptx/`, `stages/03-outline/` through `stages/05-qa-delivery/` |
| Create slide outlines | `stages/02-curriculum/output/`, `stages/03-outline/references/*`, `design-system/palette.md`, `design-system/typography.md` | `skills/pptx/`, `stages/01-extraction/`, `stages/04-generation/`, `stages/05-qa-delivery/` |
| Generate PowerPoint | `stages/03-outline/output/`, `stages/04-generation/references/*`, `design-system/*`, `skills/pptx/SKILL.md` | `stages/01-extraction/`, `stages/02-curriculum/` |
| Run QA and deliver | `stages/04-generation/output/`, `stages/05-qa-delivery/references/*`, `design-system/*` | `stages/01-extraction/`, `stages/02-curriculum/`, `stages/03-outline/` |

## Stage Handoffs

Each stage writes its output to its own `output/` folder. The next stage reads from there. If you edit an output file between stages, the next stage picks up your edits.

The typical flow is sequential (01 through 05). Users can enter at any stage depending on what they already have.

## Re-running

Re-running a stage is safe and needs none of the ceremony below: overwrite that stage's `output/`, then re-run every stage after it. The later stages will report `STALE` until you do.

Re-running the *whole* course is the case that needs care — see *Starting a New Course* above. Do not clear `output/` folders. Write the new course's files alongside the old ones under a dated subfolder, say in your report which files are current, and remove the superseded set only after the new course is delivered. If you must remove files, check referrers first: the skill's `references/reference-integrity.md` covers the search, including external ones (deploy scripts, cron, agent configs) that no walk test can see.
