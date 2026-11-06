## Setup (already done)

The skill runs against a virtualenv kept **on ext4**, not inside the skill
directory — the model volume is for weights, not ephemeral venvs. To rebuild or
extend it:

```bash
python3 -m venv ~/.venvs/markitdown-cli
~/.venvs/markitdown-cli/bin/pip install 'markitdown[all]' openai
```

The CLI re-execs into the first interpreter that can actually `import markitdown`,
checking `~/.venvs/markitdown-cli` and then a skill-local `.venv/` (for machines
that still have one), so `python3 scripts/markitdown_cli.py …` works from any shell.

`openai` is required for OCR and is **not** included in the `markitdown[all]`
extra, so install it explicitly.
