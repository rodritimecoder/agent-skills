# Writing the commit description

`-m` is where the description goes. How `git-sync` treats it:

| Your message | The commit |
| :--- | :--- |
| `type(scopes): what changed` (a conventional header) | your message, verbatim — subject and all |
| `type(scopes): what changed` with no body | your header, then a generated file manifest |
| prose without that header | diff-derived subject, your prose underneath |
| nothing | the diff-derived subject, then a generated file manifest |

Write the header when you want the commit to say what you meant. Skip it and
the diff names the subject for you, in about `chore(scope): 3 files (+4/-2)`,
which is a receipt, not a description — so the body carries the manifest of
paths that the subject only counted.

Every commit has a body, including one you leave blank: `guarded-commit`
refuses to write a subject-only message, and the push gate refuses to publish
a commit that has none.

## The standard

```
type(scope,scope): what behaviour changed

One paragraph on the first thing. One paragraph on the second, or omit it.
```

1. **Type** is one of `feat`, `fix`, `refactor`, `perf`, `docs`, `test`,
   `chore`, `build`, `ci`, `style`, `revert`.
2. **Scope** names the component a reader would recognise — the skill, crate
   or module — never a file path. Several scopes go comma-separated with no
   spaces: `fix(sync,guard,commit): …`. Three or four is fine;
   past that the change is really a `chore` or wants splitting.
3. **Subject** states what changed for a user of that component, in plain
   words. Lowercase after the colon, no trailing period. Two related things
   may share a subject joined with "and". The 72-character limit is a default,
   not a cage: a subject that actually names the change can run to ~120 before
   it stops being one line.
4. **Body** is prose paragraphs, one per concern. A paragraph carries the
   *why*, the behaviour it replaces, and the real symbols, paths or values that
   pin it down. Two to five lines each.
5. **Never** add a bullet list, a file manifest, a diffstat, a SHA list, or a
   restatement of the subject to a message *you* write. `git show --stat`
   already answers "which files"; `git log --oneline` already shows the
   subject. The generated manifest exists only where no human body does.

### A user-facing artifact

The subject and body are a user-facing artifact, not notes for someone reading the diff: they surface in changelogs and release notes and feed LLM-generated summaries. Write them for a reader who never sees the diff and has only these words to go on. Name the behaviour and the real symbols plainly, and keep each concern to one full-width paragraph.

## Worked example

```
fix(sync,guard,commit): keep a blocked file from leaving an empty commit and report the refusal

guarded_commit now propagates the refusal from publication_guard before composing the message, so a credential caught by the whole-file scan leaves nothing staged and the blocked path reaches the caller instead of an empty header.

bundle_sync records that path in its five-line receipt and exits non-zero, so a secret planted in an untracked file is named in the output rather than passing a diff-only check as silent success.
```

Three scopes, one behaviour per paragraph, a symbol in every clause, no list,
no statistics.

## For an agent

Write the `-m` before you stage, from what you changed and why:

```bash
git-sync -m "fix(github-architect): keep the description when the guard blocks

guarded_commit returned before composing the message, so a blocked file left the commit empty instead of reporting the refusal."
```

One rule to keep in mind: the subject answers *what changed for the reader*;
the body answers *why it changed and what it replaced*. Anything that merely
restates `git show --stat` belongs in neither.

## Enforced by

`git-sync check-messages --strict` and `github-architect audit --commits --strict` gate body presence plus a conventional title, user-facing prose, and full-width unwrapped paragraphs. `--strict` blocks missing bodies, non-conventional titles, placeholder jargon, bullets or manifests in author prose, hard-wrapped paragraphs, and size mismatches. Generated-manifest commits — including a conventional header with no body (Mode 2) — are reported as warnings with `severity: "warning"`, not blocks.
