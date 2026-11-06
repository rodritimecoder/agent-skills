# Drift rules

> **Status: historical design record.** The `omnicli` layer described here was
> retired on 2026-10-20 in favour of plain Agent Skills, and restored as a
> first-class skill on 2026-10-30 once it gained an executor. The code lives
> at `orchestration/omnicli/` in this repo and at
> `workstation-clis/orchestration/omnicli/`. Kept for the design record.

The drift rules are implemented in `workstation-clis/omnicli/tests/skillcheck.py`
and run with `python3 tests/skillcheck.py drift`. The catalog contract check
that sits beside them is `python3 tests/skillcheck.py contracts`.

A skill's SKILL.md and the CLI it drives are two artifacts describing the
same command surface. They drift, because one of them is written by hand.

The CLI is the truth. Its contract is extracted from the code by the
catalog builder, so it cannot be out of date. The markdown can. These
rules hold the skill to it.

## The rules

| Rule | Severity | What it catches |
| :--- | :--- | :--- |
| `flag-drift` | error | SKILL.md passes a flag the target tool does not have |
| `undocumented-flag` | warning | SKILL.md uses a flag no `references/` file in the skill explains |
| `stale-flag-doc` | warning | a `references/` flag table lists a flag no tool of the skill accepts |

`flag-drift` is an error because the command fails. The other two are
warnings: the agent has a good fallback (`omnicli describe <tool>` returns
the flag with its help text), so an incomplete reference is a quality
problem rather than a break.

## How a command is matched to a tool

The gate reads the command the same way the catalog does, and resolves it
in this order:

1. `python3 <script> [sub] [flags]` — the script's path, then its
   subcommand if the first argument names one.
2. `omnicli invoke <tool-id> -- [flags]` — the inner tool's contract, not
   omnicli's.
3. `<script>.py [sub] [flags]` — a path, relative or absolute.
4. A bare tool name.

`$VAR` bindings are expanded first, so `python3 $CLI courses --course-id 1`
resolves to the same tool as the literal form.

## The things that are not drift

Three cases look like drift and are not. Each has a rule, and each was
found by a false positive rather than by theory.

**A flag the skill's own references do not mention is a warning, not an
error.** A skill may spread its flags over several files — markitdown-cli
documents `--doctor` in `notes.md` and `--ocr` in `ocr.md` — so the test
is whether the skill *as a whole* mentions the flag, not whether one table
does.

**A flag that belongs to another program is not the tool's flag.**
`guard_hooks wrap git push --force origin main` hands `--force` to git.
A tool whose usage line ends in `...` has an argparse REMAINDER
positional: everything after the first positional belongs to the program
it wraps, and the gate stops collecting flags there.

**A command that reaches into another skill is that skill's business.**
`undocumented-flag` only applies to the skill's own tools. The other
skill's references own the documentation.

## Argparse accepts abbreviations

`--lim` is a legal spelling of `--limit` when no other flag starts with
`--lim`. A flag is accepted if the contract has it exactly, or if it is an
unambiguous prefix of exactly one contract flag. Without this the gate
reports every abbreviated flag as drift.

## What the gate cannot check

The catalog's contract is the reference, so a defect in the contract
extractor makes the gate wrong rather than the skill. That happened: the
extractor gave a subcommand its *parent's* flags, so 176 of 260
subcommand contracts were missing the flags they actually take. The gate
found them, and fixing the extractor fixed them.

A tool the catalog does not know — an external CLI, a package installed
outside the collection — cannot be checked at all. The gate skips it.
