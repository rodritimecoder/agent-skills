"""Build the omnicli catalog: skills, tools, and the FTS5 document index.

The index is a *derived artifact*. It lives outside the git repository (on
ext4, not the NTFS volume) and is rebuilt from the skill tree whenever the
fingerprint changes. Nothing in the skill collection depends on it existing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from . import policy, registry
from .textutil import expand_cjk

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "schema.sql"
ALIASES_PATH = HERE / "aliases.json"
SKILL_ROOT = HERE.parent

# Where the built catalog lives. ext4 by design: SQLite locking on the NTFS3
# mount is unreliable, and this is a rebuildable cache.
DEFAULT_DB = Path(
    os.environ.get("OMNICLI_DB")
    or (Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "omnicli" / "catalog.db")
)

MAX_CHUNK_CHARS = 2000
SECTION_RE = re.compile(r"^#{1,4}\s+(.*)$", re.MULTILINE)

# Bump when the FTS5 column layout changes; the catalog is a derived
# artifact, so the cheapest correct response is to rebuild it.
SCHEMA_VERSION = "3"


# --------------------------------------------------------------------------
# db plumbing
# --------------------------------------------------------------------------

def db_path() -> Path:
    return DEFAULT_DB


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = path or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return con


def meta_get(con: sqlite3.Connection, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _cache_interpreter(interpreter: str | None) -> str:
    """The cache key for the interpreter, carrying the parser version.

    The contract cache is keyed on the script's mtime, so a change to the
    *parser* would keep serving contracts the old parser produced. The
    parser version rides along in this opaque column so that a parser fix
    invalidates the cache without a schema change.
    """
    return f"{interpreter or ''}#p{registry.CONTRACT_PARSER_VERSION}"


def _cached_contract(con: sqlite3.Connection, path: str, mtime_ns: int,
                     interpreter: str | None) -> dict | None:
    """Return a previously extracted contract, if it is still valid.

    Validity is keyed on the file's mtime and the interpreter that was used.
    Touching a script, or running the extraction under a different Python,
    invalidates the entry.
    """
    if not mtime_ns:
        return None
    row = con.execute(
        "SELECT contract FROM contract_cache "
        "WHERE path = ? AND mtime_ns = ? AND interpreter = ?",
        (path, mtime_ns, _cache_interpreter(interpreter)),
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["contract"])
    except json.JSONDecodeError:
        return None


def _store_contract(con: sqlite3.Connection, path: str, mtime_ns: int,
                    interpreter: str | None, contract: dict) -> None:
    if not mtime_ns:
        return
    con.execute(
        "INSERT OR REPLACE INTO contract_cache"
        "(path, mtime_ns, interpreter, contract) VALUES(?,?,?,?)",
        (path, mtime_ns, _cache_interpreter(interpreter), json.dumps(contract)),
    )


def _subcommand_contract(con: sqlite3.Connection, tool: dict, sub: str,
                         parent_contract: dict | None,
                         skill_python: str | None,
                         contract_cache: dict[str, dict]) -> dict:
    """The contract for one subcommand, extracted from its own --help.

    A subcommand is a separate argparse parser with a separate flag set.
    The parent's flags are inherited by the *tool* — running the script
    still accepts them — but the parent's flags alone do not describe what
    the subcommand takes.

    Falls back to the parent's contract when the subcommand's own help
    cannot be read, so a subcommand is never left with less than it had
    before.
    """
    path = tool.get("path")
    parent = parent_contract or {}
    fallback = {
        "usage": f"{tool['argv'][-1] if tool.get('argv') else tool['id']} {sub} [options]",
        "flags": parent.get("flags", []),
        "positionals": [],
        "subcommands": [],
        "help": parent.get("help", ""),
        "parent_help_excerpt": "\n".join(parent.get("help", "").splitlines()[:12]),
    }
    if not path:
        return fallback
    try:
        path = str(Path(path).resolve())
    except OSError:
        pass

    st_mtime = 0
    try:
        st_mtime = os.stat(path).st_mtime_ns
    except OSError:
        pass

    # The cache key carries the subcommand, so a script with many
    # subcommands gets one cache entry per subcommand.
    key = f"{path}#{sub}:{st_mtime}:{skill_python}:{registry.CONTRACT_PARSER_VERSION}"
    cached = contract_cache.get(key)
    if cached is None:
        cached = _cached_contract(con, f"{path}#{sub}", st_mtime, skill_python)
    if cached is None:
        cached = registry.extract_contract(
            Path(path), python=skill_python, args=[sub])
        _store_contract(con, f"{path}#{sub}", st_mtime, skill_python, cached)
    contract_cache[key] = cached

    if not cached or not cached.get("usage"):
        return fallback
    out = dict(cached)
    # An argparse subparser inherits the parent's options. A subcommand's
    # own --help lists only the options added to that subparser, so the
    # global flags --table, --project, --out --limit --format and the
    # like are missing from it. The subcommand accepts them, so its
    # contract has to list them.
    merged = list(dict.fromkeys(
        list(parent.get("flags", [])) + list(out.get("flags", []))))
    out["flags"] = merged
    out["parent_help_excerpt"] = "\n".join(parent.get("help", "").splitlines()[:12])
    return out


def _ensure_docs_schema(con: sqlite3.Connection) -> None:
    """Recreate the FTS5 table when its column layout has drifted.

    FTS5 virtual tables cannot be ALTERed, so a column change means drop and
    rebuild. The catalog is a derived artifact, so this costs nothing but a
    few seconds.
    """
    expected = {"skill", "kind", "title", "path", "body", "aliases"}
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(docs)")}
    except sqlite3.OperationalError:
        cols = set()
    if cols and cols != expected:
        con.execute("DROP TABLE docs")
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def _ensure_tools_schema(con: sqlite3.Connection) -> None:
    """Add the enablement column to a catalog built before the gate existed.

    ALTER defaults to 1, so every tool that already existed is grandfathered:
    installing the gate must not turn a working workstation into a dead one.
    Tools discovered *after* this point start disabled (see `build`).
    """
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(tools)")}
    except sqlite3.OperationalError:
        cols = set()
    if cols and "enabled" not in cols:
        con.execute("ALTER TABLE tools ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")


# --------------------------------------------------------------------------
# chunking
# --------------------------------------------------------------------------

def split_long(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split an oversized chunk on blank lines, keeping pieces under limit."""
    if len(text) <= limit:
        return [text] if text.strip() else []
    pieces: list[str] = []
    buf: list[str] = []
    size = 0
    for para in re.split(r"\n\s*\n", text):
        if size + len(para) > limit and buf:
            pieces.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(para)
        size += len(para) + 2
    if buf:
        pieces.append("\n\n".join(buf))
    return [p for p in pieces if p.strip()]


def chunk_markdown(text: str, base_title: str) -> list[tuple[str, str]]:
    """Split markdown into (title, body) chunks along heading boundaries."""
    if not text.strip():
        return []
    matches = list(SECTION_RE.finditer(text))
    if not matches:
        return [(base_title, t) for t in split_long(text)]

    out: list[tuple[str, str]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        out.append((base_title, preamble))

    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        for part in split_long(body):
            out.append((title, part))
    return out


# --------------------------------------------------------------------------
# fingerprint
# --------------------------------------------------------------------------

def fingerprint(skills: dict[str, dict[str, Any]]) -> str:
    """Cheap hash of the skill collection, used to detect staleness.

    The builder's own source is part of the fingerprint. Without it, editing
    a rule in the builder — which script counts as a tool, how a contract is
    extracted — leaves the existing catalog in place, and ``omnicli index``
    reports success while nothing was rebuilt. The rule that decides what a
    tool is lives in the builder, so the builder's mtime is the signal.
    """
    h = hashlib.sha256()
    for source in (Path(__file__), Path(__file__).with_name("registry.py")):
        try:
            st = os.stat(source)
            h.update(f"builder:{source.name}:{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            h.update(f"builder:{source.name}:missing".encode())
    for name in sorted(skills):
        s = skills[name]
        md_path = s.get("md_path")
        if not md_path:
            # Virtual skills (the local inference endpoints) have no file on
            # disk; their content never changes, so they contribute nothing
            # to the fingerprint.
            h.update(f"{name}:virtual".encode())
            continue
        try:
            st = os.stat(md_path)
            h.update(f"{name}:{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            h.update(f"{name}:missing".encode())
    return h.hexdigest()[:16]


# --------------------------------------------------------------------------
# aliases
# --------------------------------------------------------------------------

def load_aliases() -> dict[str, dict[str, Any]]:
    if not ALIASES_PATH.is_file():
        return {}
    try:
        return json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def build(
    con: sqlite3.Connection,
    *,
    include_sidelined: bool = False,
    with_contracts: bool = True,
    progress: bool = True,
) -> dict[str, Any]:
    """(Re)build the catalog. Returns a summary dict."""
    skills = registry.load_all_skills(include_sidelined=include_sidelined)
    aliases_cfg = load_aliases()
    # A router skill's own scripts describe the endpoints it fronts, so their
    # contracts duplicate the vocabulary of the skills they route to. Indexing
    # them makes the router out-rank the specialist ("use the local llm to
    # write a script" -> omnicli instead of local-llm). Registration stays;
    # only the searchable contract text is withheld.
    no_tool_docs = {
        name for name, meta in aliases_cfg.items() if meta.get("index_tools") is False
    }

    now = time.time()
    _ensure_docs_schema(con)
    _ensure_tools_schema(con)

    # The enablement gate. A tool that is new relative to the previous
    # catalog starts disabled; everything already catalogued keeps whatever
    # state it had. The policy file wins over both, so a decision survives
    # a rebuild and a deleted catalog.
    previous = {r["id"]: r["enabled"] for r in
                con.execute("SELECT id, enabled FROM tools")}
    first_build = not previous and not meta_get(con, "built_at")

    def enabled_for(tool_id: str) -> int:
        default = bool(previous.get(tool_id, 1 if first_build else 0))
        return 1 if policy.decide(tool_id, default) else 0

    con.execute("DELETE FROM docs")
    con.execute("DELETE FROM tools")
    con.execute("DELETE FROM skills")

    doc_rows: list[tuple] = []
    tool_rows: list[tuple] = []
    contract_cache: dict[str, dict] = {}
    n_contracts = 0
    n_scripts = 0

    for name in sorted(skills):
        s = skills[name]
        meta_alias = aliases_cfg.get(name, {})
        aliases = meta_alias.get("aliases", [])
        tags = meta_alias.get("tags", [])
        # A skill may opt out of body indexing. The router itself does: its
        # documentation is *about* routing, and its example queries would
        # otherwise be indexed as high-signal routing text — the catalog
        # would end up competing with the skills it is meant to route to.
        index_body = meta_alias.get("index_body", True)

        tool_count = 0
        # A skill's own virtualenv is used to run its scripts for contract
        # extraction: a script that imports a package from that venv would
        # otherwise fail to start under the system interpreter.
        skill_python = None
        if s.get("path"):
            venv_py = Path(s["path"]) / ".venv" / "bin" / "python"
            try:
                if venv_py.is_file() and os.access(venv_py, os.X_OK):
                    skill_python = str(venv_py)
            except OSError:
                skill_python = None

        # The ~/.local/bin shim points at a copy of the skill's own script —
        # sometimes a copy in another bundle, so the paths differ even
        # though the program is the same. Giving the shim its own set of
        # subcommand children would list every subcommand twice: once under
        # `<skill>/scripts/foo` and once under `<skill>/cli`. The shim keeps
        # its contract; the children belong to the script.
        seen_script_names: set[str] = set()

        for t in registry.discover_tools(s):
            tool_count += 1
            contract = t["contract"]
            # Both a script and the ~/.local/bin shim that points at it get a
            # contract. The shim used to carry an empty one, so the contract
            # an agent received for `<skill>/cli` — the entry point it is
            # most likely to invoke — listed no flags at all.
            if with_contracts and t["kind"] in ("script", "cli") and t["path"]:
                # Resolve the shim so it is treated as the script it points
                # at: the interpreter is chosen from the resolved suffix, and
                # the cache entry is shared with the script tool.
                cpath = Path(t["path"]).resolve()
                st_mtime = 0
                try:
                    st = os.stat(cpath)
                    st_mtime = st.st_mtime_ns
                    key = f"{cpath}:{st_mtime}:{skill_python}:{registry.CONTRACT_PARSER_VERSION}"
                except OSError:
                    key = str(cpath)
                cached = contract_cache.get(key)
                if cached is None:
                    cached = _cached_contract(con, str(cpath), st_mtime, skill_python)
                if cached is None:
                    cached = registry.extract_contract(
                        cpath, python=skill_python)
                    _store_contract(con, str(cpath), st_mtime, skill_python, cached)
                    n_contracts += 1
                contract_cache[key] = cached
                contract = cached
                n_scripts += 1
                if t["kind"] == "script":
                    seen_script_names.add(cpath.name)
            tool_rows.append((
                t["id"], t["skill"], t["kind"], t["summary"], t["path"],
                json.dumps(t["argv"]), json.dumps(contract), t["parent"],
                enabled_for(t["id"]), now,
            ))

            # Subcommands become individually addressable tools. This is the
            # granularity that lets an agent pull ONE command's contract
            # instead of the whole script's surface.
            #
            # A subcommand gets its OWN contract, extracted by running
            # ``<script> <sub> --help``. It used to inherit the parent's
            # flags and help verbatim, which meant the contract an agent
            # received for `ocr/ocr:read` listed only the parent parser's
            # flags and never mentioned --pages, --output or --prompt — the
            # flags the agent actually needed. Measured across the
            # collection, that left 176 of 260 subcommand contracts
            # incomplete.
            for sub in (contract or {}).get("subcommands", []):
                if t["kind"] == "cli":
                    # The shim wraps a copy of one of this skill's own
                    # scripts. Its children would be the same commands
                    # under a second name.
                    try:
                        if Path(t["path"]).resolve().name in seen_script_names:
                            continue
                    except OSError:
                        pass
                child_id = f"{t['id']}:{sub['name']}"
                child_summary = sub.get("summary") or f"{t['id']} {sub['name']}"
                child_argv = list(t["argv"]) + [sub["name"]]
                child_contract = _subcommand_contract(
                    con, t, sub["name"], contract, skill_python,
                    contract_cache)
                tool_rows.append((
                    child_id, t["skill"], "subcommand", child_summary, t["path"],
                    json.dumps(child_argv), json.dumps(child_contract), t["id"],
                    enabled_for(child_id), now,
                ))
                tool_count += 1

        con.execute(
            "INSERT OR REPLACE INTO skills"
            "(name, dir_name, path, md_path, description, status, cli, aliases, tags, tools, indexed_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (s["name"], s["dir_name"], s["path"], s["md_path"], s["description"],
             s["status"], s["cli"], json.dumps(aliases), json.dumps(tags), tool_count, now),
        )

        # ---- documents ------------------------------------------------
        # The "skill" doc carries the description in the body, and the curated
        # aliases + tags in their own high-weight column. Both are curated by
        # the skill author — a synonym or a category label is deliberate
        # routing intent, not incidental prose — so they share a column and a
        # weight. Prose stays in the body, where incidental matches cannot
        # out-vote a precise curated signal.
        alias_text = " ".join(aliases + tags)
        tag_text = " ".join(tags)
        doc_rows.append((
            name, "skill", name, s["md_path"] or "",
            expand_cjk(" ".join(x for x in (s["description"],) if x)),
            expand_cjk(alias_text),
        ))

        md_path = s.get("md_path")
        if not md_path or not index_body:
            if progress:
                print(f"  indexed {name:<28} {tool_count:>3} tools", flush=True)
            continue

        try:
            md_text = Path(md_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            md_text = ""
        if md_text:
            body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", md_text, flags=re.DOTALL)
            for title, chunk in chunk_markdown(body, name):
                doc_rows.append((name, "body", title, md_path, expand_cjk(chunk), ""))

        for ref in sorted(Path(s["path"]).glob("references/*.md")) if s.get("path") else []:
            try:
                ref_text = ref.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for title, chunk in chunk_markdown(ref_text, ref.stem):
                doc_rows.append((name, "reference", f"{ref.stem}/{title}", str(ref), expand_cjk(chunk), ""))

        # Markdown the skill explicitly declared as part of its searchable
        # body. A skill that vendors rubrics or playbooks declares them with
        # `metadata.docs` globs; nothing is indexed that was not asked for.
        for globs in [s.get("doc_globs") or []]:
            if not globs or not s.get("path"):
                continue
            base = Path(s["path"])
            for pattern in globs:
                try:
                    matches = sorted(base.glob(pattern))
                except (ValueError, OSError):
                    continue
                for md_file in matches:
                    if not md_file.is_file() or md_file.suffix != ".md":
                        continue
                    try:
                        text = md_file.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    rel = md_file.relative_to(base).with_suffix("")
                    for title, chunk in chunk_markdown(text, md_file.stem):
                        doc_rows.append((name, "doc", f"{rel.as_posix()}/{title}",
                                         str(md_file), expand_cjk(chunk), ""))

        if progress:
            print(f"  indexed {name:<28} {tool_count:>3} tools", flush=True)

    # The local inference endpoints belong to the catalog as a whole, so they
    # are registered once — not once per skill.
    for t in registry.endpoint_tools(SKILL_ROOT):
        tool_rows.append((
            t["id"], t["skill"], t["kind"], t["summary"], t["path"],
            json.dumps(t["argv"]), json.dumps(t["contract"]), t["parent"],
            enabled_for(t["id"]), now,
        ))

    # script contracts as searchable documents
    for tool_id, skill, kind, summary, path, argv, contract_json, parent, _enabled, _ in tool_rows:
        if kind != "script" or not path or skill in no_tool_docs:
            continue
        try:
            contract = json.loads(contract_json)
        except json.JSONDecodeError:
            contract = {}
        parts = []
        if summary:
            parts.append(summary)
        if contract.get("usage"):
            parts.append(contract["usage"])
        for sub in contract.get("subcommands", []):
            label = sub["name"]
            if sub.get("aliases"):
                label += f" ({', '.join(sub['aliases'])})"
            if sub.get("summary"):
                parts.append(f"{label}: {sub['summary']}")
        if parts:
            doc_rows.append((skill, "script", tool_id, path, expand_cjk("\n".join(parts)), ""))

    con.executemany(
        "INSERT INTO docs(skill, kind, title, path, body, aliases) VALUES(?,?,?,?,?,?)", doc_rows
    )
    con.executemany(
        "INSERT OR REPLACE INTO tools"
        "(id, skill, kind, summary, path, argv, contract, parent, enabled, indexed_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)", tool_rows
    )

    meta_set(con, "fingerprint", fingerprint(skills))
    meta_set(con, "built_at", str(now))
    meta_set(con, "schema_version", SCHEMA_VERSION)
    meta_set(con, "skill_count", str(len(skills)))
    # Count what actually landed in the table. A subcommand id that collides
    # with another tool is silently replaced by INSERT OR REPLACE, so
    # len(tool_rows) can claim a tool the catalog does not have.
    meta_set(con, "tool_count", str(con.execute("SELECT count(*) FROM tools").fetchone()[0]))
    meta_set(con, "doc_count", str(len(doc_rows)))
    con.commit()

    return {
        "skills": len(skills),
        "tools": len(tool_rows),
        "docs": len(doc_rows),
        "contracts_extracted": n_contracts,
        "scripts": n_scripts,
        "built_at": now,
    }


def is_stale(con: sqlite3.Connection) -> bool:
    """True when the on-disk skills differ from what the catalog was built from."""
    skills = registry.load_all_skills(include_sidelined=False)
    return meta_get(con, "fingerprint") != fingerprint(skills)


def ensure_built(con: sqlite3.Connection, *, rebuild: bool = False,
                 with_contracts: bool = True, progress: bool = False) -> dict[str, Any]:
    """Build the catalog if missing or stale."""
    version_ok = meta_get(con, "schema_version") == SCHEMA_VERSION
    if not rebuild and version_ok and not is_stale(con):
        row = con.execute("SELECT count(*) AS c FROM skills").fetchone()
        if row and row["c"]:
            return {
                "skills": row["c"],
                "tools": int(meta_get(con, "tool_count", "0")),
                "docs": int(meta_get(con, "doc_count", "0")),
                "contracts_extracted": 0,
                "scripts": 0,
                "built_at": float(meta_get(con, "built_at", "0") or 0),
                "rebuilt": False,
            }
    summary = build(con, with_contracts=with_contracts, progress=progress)
    summary["rebuilt"] = True
    return summary
