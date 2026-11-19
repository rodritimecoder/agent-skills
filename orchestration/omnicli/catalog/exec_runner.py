"""Sandboxed JavaScript plan execution for `omnicli exec`.

A plan runs inside `node:vm` under `vm_runner.mjs`, which loads `omnicli_tools.mjs`
from `OMNICLI_BINDINGS_DIR`. Containment is bubblewrap: `write` keeps the workspace
writable and the network open, `strict` masks `$HOME` and routes every tool call
through a UNIX bridge, and `none` runs unsandboxed. Node lives under `$HOME` (nvm),
which `strict` masks, so host node and the runner are re-bound into `/tmp/omnicli`."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from catalog import bindings as bindings_mod
from catalog import bridge as bridge_mod
from catalog import builder
from catalog import invoke as invoke_mod

JS_LANGS = {"js", "javascript", "mjs", "node"}
PY_LANGS = {"py", "python"}
# Private in-sandbox mount for the host workspace. Sandboxed modes never bind
# the workspace at its host path (that collided with /tmp/omnicli and leaked
# all of host /tmp into strict mode); the host bytes arrive via a bind here.
GUEST_WORK = "/tmp/omnicli/work"
DEPRECATION = """❌ Python plans are retired in favor of JavaScript Code Mode.

  Python : omnicli exec plan.py      ← no longer supported
  JS     : omnicli exec plan.mjs
           omnicli exec -c 'const r = await search("intent")'
           omnicli spec --stubs      ← the typed surface to write against

Every tool in `omnicli_tools.mjs` is async and takes one options object, and
`emitResult(value)` returns the plan's result without scraping stdout.
"""

def bwrap_works() -> bool:
    exe = shutil.which("bwrap")
    if not exe:
        return False
    try:
        return subprocess.run([exe, "--ro-bind", "/", "/", "true"],
                              capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def _merge_exec_trace(trace: Path, start: int) -> None:
    """Copy the rows a plan wrote into the per-user usage trace."""
    try:
        fresh = [ln for ln in trace.read_text(
            encoding="utf-8", errors="ignore").splitlines()[start:] if ln.strip()]
    except OSError:
        return
    target = Path(bindings_mod.user_trace_path())
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as fh:
            fh.writelines(ln.rstrip("\n") + "\n" for ln in fresh)
    except OSError:
        pass


def _session_state_path(session: str | None) -> Path:
    """One state file per session, confined to the omnicli data directory."""
    ident = re.sub(r"[^A-Za-z0-9_-]", "_", str(session or ""))[:128] or "default"
    return Path.home() / ".local" / "share" / "omnicli" / "sessions" / f"{ident}.json"


def _load_state(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    bounded, truncated, _ = invoke_mod.cap(text, invoke_mod.DEFAULT_MAX_BYTES)
    if truncated:
        return {}
    try:
        value = json.loads(bounded)
    except (ValueError, TypeError, RecursionError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_state(path: Path, value: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, staged = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False)
        os.replace(staged, path)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise


def _deprecation_check(script: str | None, lang: str | None) -> None:
    name = (lang or "").strip().lower()
    if name in PY_LANGS or (
        not name and script and script != "-" and Path(script).suffix.lower() == ".py"
    ):
        sys.stderr.write(DEPRECATION)
        sys.exit(2)
    if name and name not in JS_LANGS:
        sys.stderr.write(f"❌ Error: unknown --lang {lang!r}; Code Mode runs JavaScript "
                         "(.mjs, .js, -c, or '-' on stdin).\n")
        sys.exit(2)

def _prepare(script: str | None, inline_code: str | None,
             workspace: str | None) -> tuple[Path, Path, bool]:
    """Return (workspace, plan path, is_inline), writing inline code to disk."""
    if workspace:
        work = Path(workspace).resolve()
    elif inline_code is not None:
        work = Path.cwd().resolve()
    else:
        work = Path(script).resolve().parent
    if not work.is_dir():
        sys.exit(f"❌ Error: workspace {work} is not a directory")
    if inline_code is None:
        script_path = Path(script).resolve()
        if not script_path.is_file():
            sys.exit(f"❌ Error: no plan script at {script_path}")
        return work, script_path, False
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mjs", prefix=".omnicli_inline_plan_",
        dir=str(work), delete=False, encoding="utf-8",
    ) as temp_plan:
        temp_plan.write(inline_code)
    return work, Path(temp_plan.name).resolve(), True


def _guest_path(path: Path, work: Path) -> str:
    """Map a host path under `work` to its private guest mount, else leave it.

    Sandboxed modes bind `work` at GUEST_WORK rather than at its host path, so
    the plan file and the trace/result/state files must be addressed through
    that mount inside the sandbox. Paths outside `work` are passed unchanged:
    `--ro-bind / /` still exposes them read-only, as before.
    """
    try:
        rel = path.resolve().relative_to(work)
    except ValueError:
        return str(path)
    return str(Path(GUEST_WORK) / rel)


def _sandboxed(node_real: Path, vm_runner: Path, bindings_dir: Path, work: Path,
               sandbox: str, script_path: Path, mem_limit: int | None, timeout: float):
    """The bwrap argv plus the bridge and runtime its teardown owns."""
    base = ["bwrap", "--die-with-parent", "--unshare-pid", "--unshare-ipc",
            "--unshare-uts", "--ro-bind", "/", "/", "--tmpfs", "/tmp",
            "--dev", "/dev", "--proc", "/proc", "--dir", "/tmp/omnicli",
            "--ro-bind", str(node_real), "/tmp/omnicli/node",
            "--ro-bind", str(vm_runner), "/tmp/omnicli/vm_runner.mjs",
            "--ro-bind", str(bindings_dir), "/tmp/omnicli/bindings"]
    if sandbox == "write":
        # Without this the child's `HOME` is the workspace, so `builder.connect()`
        # created a second, empty catalog under `<workspace>/.local` and every
        # parallel reader raced to build it. Bind the real catalog read-only
        # instead: one populated DB, no writers, no lock contention.
        db_src = builder.db_path()
        if db_src.is_file():
            base += ["--dir", "/tmp/omnicli/data",
                     "--ro-bind", str(db_src), "/tmp/omnicli/data/catalog.db",
                     "--setenv", "OMNICLI_DB", "/tmp/omnicli/data/catalog.db",
                     "--setenv", "OMNICLI_DB_RO", "1"]
            policy_src = db_src.parent / "policy.json"
            if policy_src.is_file():
                base += ["--ro-bind", str(policy_src),
                         "/tmp/omnicli/data/policy.json"]
    runtime = serving = bridge_server = None
    if sandbox == "strict":
        runtime = Path(tempfile.mkdtemp(prefix="omnicli-strict-"))
        shim = bridge_mod.write_shim(runtime / "bin")
        serving = bridge_mod.Serving(runtime / "bridge.sock",
                                     Path(sys.argv[0]).resolve(), timeout)
        bridge_server = serving.__enter__()
        base += ["--unshare-net", "--tmpfs", str(Path.home()),
                 "--ro-bind", str(shim.parent), "/tmp/omnicli/bin",
                 "--bind", str(runtime), "/tmp/omnicli/bridge",
                 "--setenv", "OMNICLI_BRIDGE", "/tmp/omnicli/bridge/bridge.sock",
                 "--setenv", "OMNICLI_BIN", "/tmp/omnicli/bin/omnicli"]
    heap = [f"--max-old-space-size={mem_limit}"] if mem_limit is not None else []
    cmd = base + ["--dir", GUEST_WORK,
                  "--bind", str(work), GUEST_WORK,
                  "--chdir", GUEST_WORK,
                  "--setenv", "HOME", GUEST_WORK,
                  "--setenv", "OMNICLI_BINDINGS_DIR", "/tmp/omnicli/bindings",
                  "/tmp/omnicli/node", "--experimental-vm-modules",
                  "--disable-warning=ExperimentalWarning", *heap,
                  "/tmp/omnicli/vm_runner.mjs", _guest_path(script_path, work)]
    if mem_limit is not None:
        if not shutil.which("prlimit"):
            sys.exit("❌ Error: --mem-limit needs prlimit (util-linux) to set RLIMIT_AS")
        # V8 reserves ~1.5 GiB of virtual address space for its CodeRange, so
        # RLIMIT_AS below 2048 MiB aborts Node before the plan starts; the JS
        # heap itself is capped exactly by --max-old-space-size above.
        cap = max(int(mem_limit), 2048) * 1024 * 1024
        cmd = ["prlimit", f"--as={cap}:{cap}", "--"] + cmd
    return cmd, serving, runtime, bridge_server


def run(script: str | None = None, code: str | None = None,
        workspace: str | None = None, out_path: str | None = None,
        sandbox: str = "write", timeout: float = 300.0, as_json: bool = False,
        max_calls: int = 100, mem_limit: int | None = None, lang: str | None = None,
        session: str | None = None):
    _deprecation_check(script, lang)
    if sandbox not in ("write", "strict", "none"):
        sys.exit(f"❌ Error: unknown sandbox mode {sandbox!r}")
    if max_calls < 0:
        sys.exit(f"❌ Error: --max-calls must be 0 (unlimited) or positive, not {max_calls}")
    if mem_limit is not None and mem_limit <= 0:
        sys.exit(f"❌ Error: --mem-limit must be a positive number of MiB, not {mem_limit}")
    if mem_limit is not None and sandbox == "none":
        sys.exit("❌ Error: --mem-limit needs a sandbox; --sandbox none runs without an rlimit")
    if not script and code is None:
        sys.exit("❌ Error: exec requires a plan script, -c/--code, or '-' from stdin.")
    if script and code is not None:
        sys.exit("❌ Error: cannot pass both a plan script and -c/--code.")

    inline_code = code if code is not None else (sys.stdin.read() if script == "-" else None)
    work, script_path, is_inline = _prepare(script, inline_code, workspace)

    node_bin = shutil.which("node")
    if not node_bin:
        sys.exit("❌ Error: Code Mode runs on node; no `node` binary on PATH.")
    node_real = Path(node_bin).resolve()
    vm_runner = Path(__file__).resolve().with_name("vm_runner.mjs")

    con = builder.connect()
    built = builder.ensure_built(con, progress=False)
    fingerprint = builder.meta_get(con, "fingerprint", "")
    bindings_dir = bindings_mod.ensure(con, fingerprint)
    # A WAL catalog keeps freshly-built rows in `-wal`; a read-only
    # `?immutable=1` reader in the child would never see them. Fold the frames
    # into the main file before the child binds it.
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    con.close()

    trace = work / ".omnicli_trace.jsonl"
    # One workspace keeps one trace log; count only rows this run appends.
    seen = len([ln for ln in trace.read_text(encoding="utf-8").splitlines() if ln.strip()]) \
        if trace.is_file() else 0
    result_file = work / ".omnicli_result.json"
    result_file.unlink(missing_ok=True)

    sid = session or bindings_mod.trace_identity()[1]
    state_path = _session_state_path(sid)
    state_file = work / ".omnicli_state.json"
    state_file.unlink(missing_ok=True)
    state_file.write_text(
        json.dumps(_load_state(state_path), ensure_ascii=False), encoding="utf-8")

    env = os.environ.copy()
    env.update({
        "OMNICLI_BIN": shutil.which("omnicli") or str(Path(sys.argv[0]).resolve()),
        "OMNICLI_TRACE": str(trace),
        "OMNICLI_RESULT": str(result_file),
        "OMNICLI_STATE": str(state_file),
        "OMNICLI_MAX_CALLS": str(max_calls),
        "OMNICLI_TRUST_INDEX": "1",
    })

    heap = [f"--max-old-space-size={mem_limit}"] if mem_limit is not None else []
    cmd = [str(node_real), "--experimental-vm-modules",
           "--disable-warning=ExperimentalWarning", *heap,
           str(vm_runner), str(script_path)]
    runtime: Path | None = None
    serving = None
    bridge_server = None
    sandboxed = sandbox != "none"
    if sandbox == "none":
        env["OMNICLI_BINDINGS_DIR"] = str(bindings_dir)
    else:
        if not bwrap_works():
            sys.exit("❌ Error: bubblewrap is not available; pass --sandbox none to run unsandboxed.")
        for key, path in (("OMNICLI_TRACE", trace), ("OMNICLI_RESULT", result_file),
                          ("OMNICLI_STATE", state_file)):
            env[key] = _guest_path(path, work)
        cmd, serving, runtime, bridge_server = _sandboxed(
            node_real, vm_runner, bindings_dir, work, sandbox, script_path,
            mem_limit, timeout)

    started = time.time()
    if os.environ.get("OMNICLI_EXEC_DEBUG"):
        print(" ".join(cmd), file=sys.stderr)
    saved_state = None
    try:
        proc = subprocess.run(cmd, cwd=str(work), env=env, capture_output=True,
                              text=True, timeout=timeout)
        try:
            candidate = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            candidate = None
        if isinstance(candidate, dict):
            saved_state = candidate
    except subprocess.TimeoutExpired:
        sys.exit(f"❌ Error: plan exceeded {timeout:g}s")
    finally:
        if is_inline and script_path.is_file():
            script_path.unlink(missing_ok=True)
        state_file.unlink(missing_ok=True)
        if serving is not None:
            serving.__exit__()
        if runtime is not None:
            shutil.rmtree(runtime, ignore_errors=True)
    if saved_state is not None:
        _save_state(state_path, saved_state)
    elapsed = time.time() - started

    stderr_text = proc.stderr
    if proc.returncode != 0 and mem_limit is not None and any(
        hint in proc.stderr.lower()
        for hint in ("out of memory", "allocation failed", "memoryerror")
    ):
        stderr_text += (f"\n[omnicli] this plan ran under --mem-limit {mem_limit} MiB "
                        "(--max-old-space-size), so the allocation failure above is "
                        "the cap, not the plan's logic.\n")

    calls = 0
    rows = []
    if trace.is_file():
        rows = [ln for ln in trace.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for line in rows[seen:]:
        try:
            kind = json.loads(line).get("kind")
        except (ValueError, AttributeError):
            kind = None
        if kind in (None, "call"):
            calls += 1

    # Same byte budget bounds both emitResult and stdout; --out keeps full stdout.
    stdout_budget = 7000 if as_json else 7800

    result = None
    result_truncated = False
    result_bytes = 0
    if result_file.is_file():
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        result_file.unlink(missing_ok=True)
    if result is not None:
        # Cap the emitResult() channel like stdout; small results pass through unchanged.
        shown_result, result_truncated, result_bytes = invoke_mod.cap(
            json.dumps(result, ensure_ascii=False), stdout_budget)
        if result_truncated:
            result = shown_result

    if out_path:
        target = Path(out_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(proc.stdout, encoding="utf-8")

    bridge_calls = getattr(bridge_server, "calls", 0)
    # Bound what re-enters the model; --out preserves full stdout when requested.
    shown_stdout, stdout_truncated, stdout_bytes = invoke_mod.cap(proc.stdout, stdout_budget)
    report = {
        "plan": "<stdin>" if script == "-" else ("<inline>" if code is not None else str(script_path)),
        "sandboxed": sandboxed,
        "sandbox": sandbox,
        "mem_limit": mem_limit,
        "exit_code": proc.returncode,
        "seconds": round(elapsed, 3),
        "tool_calls": calls,
        "bridge_calls": bridge_calls,
        "bridge_denied": getattr(bridge_server, "denied", []),
        "tools": built.get("tools"),
        "result": result,
        "result_truncated": result_truncated,
        "result_bytes": result_bytes,
        "stdout": shown_stdout,
        "stdout_truncated": stdout_truncated,
        "stdout_bytes": stdout_bytes,
        "stderr": stderr_text[-2000:],
    }
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        sys.stdout.write(shown_stdout)
        bridge_note = f" · bridge={bridge_calls} call(s)" if bridge_calls else ""
        print(f"⚡ [exec] {calls} tool call(s) in one turn · {elapsed:.2f}s "
              f"· sandbox={sandbox}{bridge_note}", file=sys.stderr)
    if stderr_text and (not as_json or proc.returncode != 0):
        sys.stderr.write(stderr_text if stderr_text.endswith("\n") else stderr_text + "\n")
    _merge_exec_trace(trace, seen)
    sys.exit(proc.returncode)
