#!/usr/bin/env python3
"""agent-relay: two-way messages between coding-agent sessions in Claude Code, Codex, OpenCode, Factory Droid
and Google Antigravity CLI (agy). Local only; Python standard library only.

Usage: python -I relay.py <command> ...
  doctor                         the harness CLIs found here, their versions, and this session (whoami)
  whoami                         this agent's harness, session id and folder (and its alias, if registered)
  register <alias> [--kind K --session ID --cwd DIR]
                                 remember a session under a name; with no --kind/--session, this session (and,
                                 if it runs in an open window, that window: `send` then refuses and says use `tell`)
  names | forget <alias>         list or drop remembered sessions
  new <kind> --cwd DIR --alias A [opts] (MESSAGE... | --file F)
                                 start a session in DIR with a message, wait for its turn, print the reply
  send <alias> [opts] (MESSAGE... | --file F)
                                 resume a remembered session with a message, wait for its turn, print the reply
  tell <to> [--from NAME] (MESSAGE... | --file F)
                                 leave a message in <to>'s inbox and return at once
  inbox <name> [--peek]          print <name>'s waiting mail and file it under read/ (--peek: leave it)
  watch <name> [--hours H] [--every S]
                                 wait until mail for <name> arrives, print it, exit 0; exit 2 if none came
  panel --brief F --cwd DIR --party kind[:model[:effort]] (2 to 6 times) [--rounds N] [--moderator kind[:model]]
                                 several agents answer one question blind, then cross-examine each other's
                                 answers; an optional moderator writes the synthesis; transcript in panels/
opts (new/send): --from NAME  --access read|write|full  --model M  --effort E  --timeout MIN  --wait MIN
                 --force  --json
kinds: claude, codex, opencode, droid, agy
State: $AGENT_RELAY_HOME or ~/.agent-relay (sessions.json, log.md, messages/, inbox/<name>/, busy/).
"""
import argparse
import datetime as dt
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

KINDS = ("claude", "codex", "opencode", "droid", "agy")
WIN = os.name == "nt"
USER = Path.home()
HOME = Path(os.environ.get("AGENT_RELAY_HOME") or USER / ".agent-relay").expanduser()
REG, LOG, MSGS, INBOX, BUSY = HOME / "sessions.json", HOME / "log.md", HOME / "messages", HOME / "inbox", HOME / "busy"
SELF = Path(__file__).resolve()
NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,40}")
SECRET = re.compile(r"\b(sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"
                    r"|AIza[0-9A-Za-z_-]{30,}|xox[abpr]-[A-Za-z0-9-]{10,})")
ARGV_MAX = 24000  # longer messages go by file: Windows caps a command line at 32,767 characters

# The variable each harness sets for the tools it runs, naming the session they run in.
SESSION_VAR = {"claude": "CLAUDE_CODE_SESSION_ID", "codex": "CODEX_THREAD_ID", "opencode": "OPENCODE_SESSION_ID",
               "droid": "FACTORY_SESSION_ID", "agy": "ANTIGRAVITY_CONVERSATION_ID"}
# The process names that mark a harness in this process's ancestry (nearest one wins).
PROC = {"claude": ("claude",), "codex": ("codex",), "opencode": ("opencode",), "droid": ("droid",),
        "agy": ("agy", "antigravity")}
# A child must not inherit its parent's session identity (it would think it is the parent), nor its tokens.
SCRUB_EXACT = {"CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "AI_AGENT", "AGENT", "OPENCODE", "OPENCODE_TERMINAL",
               "DROID_PROTECTED_PID", "FACTORY_DISABLE_SETTINGS_PERSISTENCE", "CODEX_CI", "CODEX_PERMISSION_PROFILE",
               "CODEX_TOOL_CALL_ID", "CODEX_SESSION_ID", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED"}
SCRUB_PREFIX = ("CLAUDE_CODE_SESSION", "CLAUDE_CODE_CHILD", "CLAUDE_CODE_MESSAGING", "CLAUDE_CODE_ENTRYPOINT",
                "CLAUDE_CODE_EXECPATH", "ANTIGRAVITY_", "OPENCODE_SESSION", "FACTORY_SESSION")


# ---------- small helpers

def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def stamp():
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]


def mask(text):
    return SECRET.sub("***", text or "")


def short(text, n=160):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def die(msg, code=1):
    print(f"relay: {msg}", file=sys.stderr)
    sys.exit(code)


def name_ok(name, what):
    if not NAME_RE.fullmatch(name or ""):
        die(f"{what} must be 1 to 40 letters, digits, dots, dashes or underscores: {name!r}")
    return name


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def log(way, sender, target, where, text, reply=None, extra=""):
    MSGS.mkdir(parents=True, exist_ok=True)
    st = stamp()
    (MSGS / f"{st}-{target}-{way}.txt").write_text(mask(text), encoding="utf-8")
    if reply is not None:
        (MSGS / f"{st}-{target}-reply.txt").write_text(mask(reply), encoding="utf-8")
    line = f"- {now()} {way} {sender} -> {target} ({where}): {short(mask(text))}"
    if reply is not None:
        line += f" | reply: {short(mask(reply))}"
    if extra:
        line += f" | {extra}"
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def registry():
    try:
        return json.loads(REG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def remember(alias, kind, session, cwd, **extra):
    reg = registry()
    entry = {"kind": kind, "session": session, "cwd": cwd, "added": now()}
    entry.update({k: v for k, v in extra.items() if v})
    reg[alias] = entry
    write_atomic(REG, json.dumps(reg, indent=2))


def alias_of(kind, session):
    return next((a for a, e in registry().items() if e.get("kind") == kind and e.get("session") == session), None)


def child_env(cwd):
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in SCRUB_EXACT and not k.upper().startswith(SCRUB_PREFIX) and k not in SESSION_VAR.values()}
    env["PWD"] = str(cwd)  # OpenCode takes its project folder from PWD, not from the process's working folder
    return env


def run(cmd, cwd, stdin_text=None, timeout_min=None):
    try:
        r = subprocess.run(cmd, cwd=str(cwd), input=stdin_text if stdin_text is not None else None,
                           stdin=None if stdin_text is not None else subprocess.DEVNULL, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=child_env(cwd),
                           timeout=timeout_min * 60 if timeout_min else None)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, out, f"timed out after {timeout_min} min; the turn may still be running in the harness"
    except FileNotFoundError as e:
        return 127, "", str(e)


def json_lines(text):
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                yield json.loads(line)
            except ValueError:
                continue


def last_json(text):
    found = list(json_lines(text))
    if found:
        return found[-1]
    try:
        return json.loads(text)
    except ValueError:
        return {}


# ---------- processes

def pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if WIN:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def process_table():
    """{pid: (parent pid, lower-case name without .exe)} for every process, or {} if it cannot be read."""
    table = {}
    try:
        if WIN:
            ps = ("Get-CimInstance Win32_Process | ForEach-Object { [string]$_.ProcessId + [char]9 + "
                  "[string]$_.ParentProcessId + [char]9 + $_.Name }")
            out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=30).stdout
            rows = (line.split("\t") for line in out.splitlines())
        else:
            out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,comm="], capture_output=True, text=True,
                                 timeout=30).stdout
            rows = (line.split(None, 2) for line in out.splitlines())
        for row in rows:
            if len(row) == 3 and row[0].strip().isdigit() and row[1].strip().isdigit():
                name = Path(row[2].strip()).name.lower()
                table[int(row[0])] = (int(row[1]), name[:-4] if name.endswith(".exe") else name)
    except (OSError, subprocess.SubprocessError):
        pass
    return table


def kind_of(name):
    for kind, names in PROC.items():
        if name in names or any(name.startswith(n + "-") or name.startswith(n + ".") for n in names):
            return kind
    return None


def harness_proc(kind=None, table=None):
    """(kind, pid) of the nearest harness process above this one (of `kind`, if given), or (None, None). The pid is
    the top of that harness's own chain of processes, because Codex runs commands through helper processes."""
    table, pid, seen, found = table or process_table(), os.getpid(), set(), None
    while pid in table and pid not in seen:
        seen.add(pid)
        pid = table[pid][0]
        k = kind_of(table.get(pid, (0, ""))[1])
        if found:
            if k != found[0]:
                break
            found = (k, pid)
        elif k and kind in (None, k):
            found = (k, pid)
    return found or (None, None)


def nearest_harness():
    """The harness whose process is this process's nearest ancestor, or None."""
    return harness_proc()[0]


def window_open(alias, kind):
    """The pid of the window a session was registered from, while that window is still open; else None.
    OpenCode is left out: its windows share one service, so a relayed turn shows in the window."""
    pid = (registry().get(alias) or {}).get("window_pid")
    if kind == "opencode" or not pid or not pid_alive(pid):
        return None
    return pid if kind_of(process_table().get(int(pid), (0, ""))[1]) == kind else None  # not a reused pid


# ---------- where things are

def find_bin(kind):
    override = os.environ.get(f"AGENT_RELAY_{kind.upper()}_BIN")
    if override:
        return override
    if kind == "codex" and WIN:
        # The npm and pnpm `codex` launchers are .cmd/shell shims; message text through cmd.exe is unsafe, so find
        # the native codex.exe they launch.
        pats = ["AppData/Roaming/npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe",
                "AppData/Roaming/npm/node_modules/@openai/codex/vendor/*/bin/codex.exe",
                "AppData/Local/pnpm/global/*/*/node_modules/.pnpm/@openai+codex@*/node_modules/@openai/codex*/vendor/*/bin/codex.exe",
                "AppData/Local/pnpm/global/*/node_modules/.pnpm/@openai+codex@*/node_modules/@openai/codex*/vendor/*/bin/codex.exe"]
        hits = [p for pat in pats for p in USER.glob(pat)]
        if hits:
            # Codex's sandbox starts codex-resources\codex-windows-sandbox-setup.exe beside its vendor folder; a
            # path past MAX_PATH (260) fails with "os error 3", so prefer a copy whose helper path fits, then the newest.
            def rank(p):
                helper = p.parent.parent / "codex-resources" / "codex-windows-sandbox-setup.exe"
                return (len(str(helper)) < 260, p.stat().st_mtime)
            return str(max(hits, key=rank))
    names = {"agy": ("agy", "antigravity")}.get(kind, (kind,))
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    if kind == "claude":
        for cand in (USER / ".local/bin/claude.exe", USER / ".local/bin/claude", USER / ".claude/local/claude"):
            if cand.exists():
                return str(cand)
    if kind == "agy":
        cand = USER / "AppData/Local/agy/bin/agy.exe"
        if cand.exists():
            return str(cand)
    return None


def need_bin(kind):
    b = find_bin(kind)
    if not b:
        die(f"{kind} CLI not found on PATH (set AGENT_RELAY_{kind.upper()}_BIN to its path)")
    return b


def shim(path):
    return WIN and str(path).lower().endswith((".cmd", ".bat"))


def oc_get(sid, cwd=None):
    """An OpenCode session's data from the running service (opencode api), or None."""
    b = find_bin("opencode")
    if not b:
        return None
    code, out, _ = run([b, "api", "session.get", "--param", f"sessionID={sid}"], cwd or USER, timeout_min=1)
    d = (last_json(out) or {}).get("data") if code == 0 else None
    if not d:
        return None
    t, m = d.get("time") or {}, d.get("model") or {}
    model = f"{m.get('providerID')}/{m.get('id')}" + (f"#{m['variant']}" if m.get("variant") else "") if m else None
    return {"cwd": (d.get("location") or {}).get("directory") or d.get("directory"), "agent": d.get("agent"),
            "model": model, "parent": d.get("parentID"), "archived": t.get("archived"),
            "busy": (t.get("busy") or 0) > (t.get("idle") or 0)}


def droid_dir(cwd):
    return USER / ".factory/sessions" / ("-" + str(cwd).replace(":", "").replace("\\", "-").replace("/", "-"))


def session_cwd(kind, sid):
    """The folder a session started in, from the harness's own session records, or None."""
    try:
        if kind == "claude":
            for f in (USER / ".claude/projects").glob(f"*/{sid}.jsonl"):
                with f.open(encoding="utf-8", errors="replace") as fh:
                    for _, line in zip(range(200), fh):
                        m = re.search(r'"cwd":"((?:[^"\\]|\\.)*)"', line)
                        if m:
                            return json.loads(f'"{m.group(1)}"')
        elif kind == "codex":
            for f in (USER / ".codex/sessions").rglob(f"rollout-*{sid}.jsonl"):
                with f.open(encoding="utf-8") as fh:
                    return (json.loads(fh.readline() or "{}").get("payload") or {}).get("cwd")
        elif kind == "droid":
            for f in (USER / ".factory/sessions").glob(f"*/{sid}.jsonl"):
                with f.open(encoding="utf-8") as fh:
                    return json.loads(fh.readline() or "{}").get("cwd")
        elif kind == "opencode":
            d = oc_get(sid)
            return d and d["cwd"]
    except (OSError, ValueError):
        pass
    return None


@functools.lru_cache(maxsize=1)
def whoami():
    """(kind, session id, folder) of the agent session running this command, or (None, None, cwd)."""
    present = {k: os.environ[v] for k, v in SESSION_VAR.items() if os.environ.get(v)}
    kind = None
    if len(present) == 1:
        kind = next(iter(present))
    elif present:  # several are set when one harness started another: the nearest ancestor is the one we are in
        near = nearest_harness()
        kind = near if near in present else next(k for k in ("opencode", "droid", "agy", "codex", "claude")
                                                  if k in present)
    if not kind:
        return None, None, os.getcwd()
    sid = present[kind]
    return kind, sid, session_cwd(kind, sid) or os.getcwd()


# ---------- busy marks (a session waiting on a relay reply, or being run by one)

def busy_dir(kind, sid):
    return BUSY / f"{kind}-{re.sub(r'[^A-Za-z0-9_.-]', '_', sid)}"


def busy_holder(kind, sid):
    """A live mark on the session (one file per relay process holding it), or None; dead holders are swept."""
    folder = busy_dir(kind, sid)
    for p in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if pid_alive(d.get("pid")):
            return d
        p.unlink(missing_ok=True)
    return None


def mark_busy(kind, sid, why):
    if sid:
        write_atomic(busy_dir(kind, sid) / f"{os.getpid()}.json",
                     json.dumps({"pid": os.getpid(), "since": now(), "why": why}))


def unmark(kind, sid):
    if sid:
        (busy_dir(kind, sid) / f"{os.getpid()}.json").unlink(missing_ok=True)


# ---------- the five harnesses. Each returns (exit code, session id, reply text, stats, stderr).

ACCESS = {  # what --access means in each harness
    "claude": {"read": ["--permission-mode", "default"],
               "write": ["--permission-mode", "acceptEdits", "--allowedTools", "Bash"],
               "full": ["--permission-mode", "bypassPermissions"]},
    "codex": {"read": "read-only", "write": "workspace-write", "full": "danger-full-access"},
    "opencode": {"read": [], "write": ["--auto"], "full": ["--auto"]},
    "droid": {"read": [], "write": ["--auto", "medium"], "full": ["--auto", "high"]},
    # agy headless: accept-edits auto-denies every command, and auto is not offered to every account (measured
    # 26 Nov 2026, agy 1.5.18), so write is agy's default mode, which runs commands its policy finds safe.
    "agy": {"read": ["--mode", "plan"], "write": [], "full": ["--dangerously-skip-permissions"]},
}


def run_claude(cwd, msg, sid, model, effort, access, timeout):
    cmd = [need_bin("claude"), "-p", "--output-format", "json"]
    cmd += (["--resume", sid] if sid else []) + (["--model", model] if model else [])
    cmd += (["--effort", effort] if effort else []) + (ACCESS["claude"][access] if access else [])
    code, out, err = run(cmd, cwd, stdin_text=msg, timeout_min=timeout)  # by stdin: no argv quoting or length limit
    d = last_json(out)
    reply = d.get("result") or ""
    if d.get("is_error") and code == 0:
        code = 1
    stats = f"exit {code}, cost ${d.get('total_cost_usd')}, turns {d.get('num_turns')}"
    return code, d.get("session_id") or sid, reply, stats, err


def run_codex(cwd, msg, sid, model, effort, access, timeout):
    exe = need_bin("codex")
    out_file = Path(tempfile.mkdtemp(prefix="relay-cx-")) / "last.txt"
    cmd = [exe, "exec", "--json", "--skip-git-repo-check", "-o", str(out_file)]
    sandbox = ACCESS["codex"].get(access) if access else None
    for key, value in (("model", model), ("model_reasoning_effort", effort), ("sandbox_mode", sandbox)):
        if value:
            cmd += ["-c", f'{key}="{value}"']
    if sandbox:
        cmd += ["-c", 'approval_policy="never"']  # exec cannot ask; never hang waiting for an approval
    if sandbox == "workspace-write":  # let it write its replies into the relay's inbox
        cmd += ["-c", f"sandbox_workspace_write.writable_roots=['{HOME}']"]
    long = len(msg) > ARGV_MAX  # a long message goes on stdin ("-" as the prompt), past the command-line limit
    cmd += (["resume", sid] if sid else ["-C", str(cwd)]) + ["-" if long else msg]
    code, out, err = run(cmd, cwd, stdin_text=msg if long else None, timeout_min=timeout)
    tid, usage, errors = sid, {}, []
    for e in json_lines(out):
        tid = e.get("thread_id") or tid
        if e.get("type") == "turn.completed":
            usage = e.get("usage") or usage
        if e.get("type") in ("error", "turn.failed"):
            errors.append(str(e.get("message") or e.get("error")))
    reply = out_file.read_text(encoding="utf-8", errors="replace") if out_file.exists() else ""
    shutil.rmtree(out_file.parent, ignore_errors=True)
    stats = f"exit {code}, tokens in {usage.get('input_tokens')} out {usage.get('output_tokens')}"
    return code, tid, reply, stats, (err + ("\n" + "\n".join(errors) if errors else "")).strip()


def run_opencode(cwd, msg, sid, model, effort, access, timeout, agent=None, title=None):
    cmd = [need_bin("opencode"), "run", "--format", "json"]
    if model and effort and "#" not in model:
        model = f"{model}#{effort}"  # OpenCode names a model's effort as its variant
    for flag, value in (("--session", sid), ("-m", model), ("--agent", agent), ("--title", title)):
        if value:
            cmd += [flag, value]
    if len(msg) > ARGV_MAX:  # attach a long message as a file: attachments need no read permission
        cmd += ["-f", str(msg_file(msg))]
        msg = "The whole message is in the attached file. Act on it as if it had been typed here."
    cmd += (ACCESS["opencode"][access] if access else []) + [msg]
    code, out, err = run(cmd, cwd, timeout_min=timeout)
    texts, cost, tokens, new_sid = [], 0.0, {}, sid
    for e in json_lines(out):
        part = e.get("part") or {}
        new_sid = e.get("sessionID") or new_sid
        if e.get("type") == "text" and part.get("text"):
            texts.append(part["text"])
        if e.get("type") == "step_finish":
            cost += part.get("cost") or 0
            tokens = part.get("tokens") or tokens
        if e.get("type") == "error":
            err += "\n" + json.dumps(e.get("error") or e)[:600]
    stats = f"exit {code}, cost {cost}, tokens in {tokens.get('input')} out {tokens.get('output')}"
    return code, new_sid, "\n".join(texts), stats, err


def run_droid(cwd, msg, sid, model, effort, access, timeout):
    cmd = [need_bin("droid"), "exec", "--cwd", str(cwd), "-o", "json"]
    for flag, value in (("-s", sid), ("-m", model), ("-r", effort)):
        if value:
            cmd += [flag, value]
    cmd += (ACCESS["droid"][access] if access else [])
    cmd += ["-f", str(msg_file(msg))] if len(msg) > ARGV_MAX else [msg]  # droid exec -f reads the prompt from a file
    code, out, err = run(cmd, cwd, timeout_min=timeout)
    d = last_json(out)
    usage = d.get("usage") or {}
    stats = f"exit {code}, factory credits {usage.get('factory_credits')}"
    return code, d.get("session_id") or sid, d.get("result") or "", stats, err


def run_agy(cwd, msg, sid, model, effort, access, timeout):
    cmd = [need_bin("agy"), "-p", msg, "--output-format", "json"]
    for flag, value in (("--conversation", sid), ("--model", model), ("--effort", effort)):
        if value:
            cmd += [flag, value]
    cmd += ACCESS["agy"][access] if access else []
    code, out, err = run(cmd, cwd, timeout_min=timeout)
    d = last_json(out)
    if d.get("status") and d.get("status") != "SUCCESS" and code == 0:
        code = 1
    usage = d.get("usage") or {}
    stats = f"exit {code}, status {d.get('status')}, tokens in {usage.get('input_tokens')} out {usage.get('output_tokens')}"
    denied = sorted({x.get("action") or "?" for x in d.get("denied_actions") or []})
    if denied:  # headless agy cannot ask, so it denies; say so instead of returning an unexplained empty reply
        stats += f", denied: {', '.join(denied)} (try --access full)"
        err = (err + f"\nagy denied these actions: {', '.join(denied)}").strip()
    return code, d.get("conversation_id") or sid, d.get("response") or "", stats, err


RUNNERS = {"claude": run_claude, "codex": run_codex, "opencode": run_opencode, "droid": run_droid, "agy": run_agy}


# ---------- messages

def body_of(a):
    body = Path(a.file).read_text(encoding="utf-8") if a.file else " ".join(a.message)
    if not body.strip():
        die("empty message")
    return body.strip()


def sender_of(a):
    if getattr(a, "from_", None):
        return name_ok(a.from_, "--from")
    kind, sid, _ = whoami()
    if kind:
        return alias_of(kind, sid) or f"{kind}-{sid[:8]}"
    return "user"


def compose(sender, body):
    kind, sid, cwd = whoami()
    origin = f" ({kind} session {sid}, in {cwd})" if kind else ""
    py = "python" if WIN else "python3"
    head = f"[agent-relay: a message from \"{sender}\"{origin}, another agent on this machine.]"
    foot = (f"[agent-relay: your reply in this turn goes back to \"{sender}\" by itself. To write to them later, run: "
            f"{py} -I \"{SELF}\" tell {sender} --from <your name> \"<text>\". Who else can be reached: "
            f"{py} -I \"{SELF}\" names.]")
    return f"{head}\n{body}\n\n{foot}"


def msg_file(text):
    MSGS.mkdir(parents=True, exist_ok=True)
    f = MSGS / f"{stamp()}-message.md"
    f.write_text(text, encoding="utf-8")
    return f


def deliverable(kind, text):
    """Claude, Codex, OpenCode and Droid take a long message on stdin or as a file themselves. A long message for
    agy, and any message for a .cmd/.bat launcher, becomes a pointer to a file, so argv stays short and plain."""
    if not shim(find_bin(kind) or "") and (kind != "agy" or len(text) <= ARGV_MAX):
        return text
    return f"Read the message in the file {msg_file(text)} and act on it as if it had been typed here."


def show(a, alias, kind, sid, reply, stats, err, code):
    if getattr(a, "json", False):
        print(json.dumps({"alias": alias, "kind": kind, "session": sid, "exit": code, "reply": reply, "stats": stats,
                          "stderr": short(err, 2000) if code else ""}, ensure_ascii=False))
        return
    print(f"--- reply from {alias} ({kind} {sid}; {stats})")
    print((reply or "").strip() or "(no text)")
    if code != 0 and err:
        print("--- stderr:", short(err, 1200))


def converse(a, alias, kind, sid, cwd, access, extra=None):
    """Deliver one message as a turn, wait for it to end, log both sides; returns the process exit code."""
    sender = sender_of(a)
    text = compose(sender, body_of(a))
    me_kind, me_sid, _ = whoami()
    window = window_open(alias, kind) if sid and not a.force else None
    if window:
        print(f"relay: {alias} is open in a {kind} window (pid {window}). A turn sent now would run in a separate "
              "process that the window never sees, and the conversation would split in two. Nothing sent. Use "
              f"`tell {alias}` instead; that window reads it with `inbox {alias}` (or `watch {alias}` in the "
              "background). --force sends anyway.")
        return 3
    if sid:
        deadline = time.time() + 60 * (a.wait or 0)
        while True:
            holder = busy_holder(kind, sid)
            oc = oc_get(sid) if kind == "opencode" else None
            if kind == "opencode":
                if not oc:
                    die(f"OpenCode session {sid} not found (is `opencode` working here?)")
                if oc["parent"] or oc["archived"]:
                    die("refused: that OpenCode session is a subagent (child) or archived session")
            why = (f"waiting on a relay reply or being run by one (pid {holder['pid']}, since {holder['since']})"
                   if holder else "busy with a turn (OpenCode says so)" if oc and oc["busy"] else None)
            if not why or a.force:
                break
            if time.time() >= deadline:
                print(f"relay: {alias} is {why}; nothing sent. Use `tell {alias}` to leave it mail instead, "
                      "or add --wait MIN.")
                return 3
            time.sleep(15)
        if kind == "opencode":
            extra = dict(extra or {}, agent=oc["agent"])
            if not a.model:
                a.model = oc["model"]
            cwd = oc["cwd"] or cwd
    if me_kind:
        mark_busy(me_kind, me_sid, f"waiting on {alias}")
    mark_busy(kind, sid, f"turn from {sender}")
    try:
        msg = deliverable(kind, text)
        runner = RUNNERS[kind]
        kwargs = extra or {}
        code, new_sid, reply, stats, err = runner(cwd, msg, sid, a.model, a.effort, access, a.timeout, **kwargs)
    finally:
        unmark(kind, sid)
        if me_kind:
            unmark(me_kind, me_sid)
    if new_sid and not sid:
        remember(alias, kind, new_sid, str(cwd), access=access, model=a.model, effort=a.effort)
    log("sent", sender, alias, f"{kind} {new_sid or sid}{' (new)' if not sid else ''}", text, reply, stats)
    show(a, alias, kind, new_sid or sid, reply, stats, err, code)
    return 0 if code == 0 and (reply or "").strip() else 5


# ---------- commands

def cmd_doctor(a):
    print(f"relay home: {HOME}")
    for kind in KINDS:
        b = find_bin(kind)
        ver = ""
        if b:
            code, out, err = run([b, "--version"], USER, timeout_min=1)
            ver = short((out or err).strip().splitlines()[0] if (out or err).strip() else f"exit {code}", 80)
        print(f"{kind:9} {b or 'not found'}{'  ' + ver if ver else ''}{'  (a .cmd shim: messages go by file)' if b and shim(b) and kind != 'codex' else ''}")
    cmd_whoami(a)
    return 0


def cmd_whoami(a):
    kind, sid, cwd = whoami()
    if not kind:
        print(f"this is not an agent session that relay recognises (folder {cwd})")
        return 2
    alias = alias_of(kind, sid)
    print(f"{kind} session {sid} in {cwd}" + (f", registered as {alias}" if alias else ", not registered"))
    return 0


def cmd_register(a):
    alias = name_ok(a.alias, "alias")
    if bool(a.kind) != bool(a.session):
        die("give both --kind and --session, or neither (to register this session)")
    window = None
    if a.kind:
        kind, sid = a.kind, a.session
        cwd = a.cwd or session_cwd(kind, sid)
    else:
        kind, sid, cwd = whoami()
        if not kind:
            die("this is not an agent session relay recognises; give --kind and --session")
        cwd = a.cwd or cwd
        found, pid = harness_proc(kind)
        window = pid if found == kind and kind != "opencode" else None
    if kind == "opencode":
        d = oc_get(sid)
        if not d:
            die(f"no OpenCode session {sid}")
        if d["parent"]:
            die("refused: that is an OpenCode subagent (child) session")
        cwd = cwd or d["cwd"]
    if not cwd:
        die("give --cwd, the folder the session works in")
    remember(alias, kind, sid, str(cwd), window_pid=window)
    print(f"{alias}: {kind} {sid} in {cwd}")
    if window:
        print(f"While {kind} process {window} runs, `send {alias}` is refused: others reach this session with "
              f"`tell {alias}`, and it reads its mail with `inbox {alias}` or `watch {alias}`.")
    elif kind == "opencode" and not a.kind:
        print(f"Others can `send {alias}`: the turn shows in this OpenCode window and the reply goes back to them.")
    return 0


def cmd_names(a):
    reg = registry()
    if not reg:
        print("no sessions registered")
    for alias, v in reg.items():
        more = ", ".join(f"{k} {v[k]}" for k in ("access", "model") if v.get(k))
        if window_open(alias, v["kind"]):
            more = ", ".join(filter(None, [more, "open in a window: use tell, not send"]))
        print(f"{alias}: {v['kind']} {v['session']} in {v['cwd']} (since {v['added']}{'; ' + more if more else ''})")
    return 0


def cmd_forget(a):
    reg = registry()
    if reg.pop(a.alias, None) is None:
        die(f"no session named {a.alias}")
    write_atomic(REG, json.dumps(reg, indent=2))
    print(f"forgot {a.alias}")
    return 0


def cmd_new(a):
    alias = name_ok(a.alias, "--alias")
    if alias in registry() and not a.force:
        die(f"{alias} is already registered; pick another alias, `forget` it, or add --force")
    cwd = Path(a.cwd).resolve()
    if not cwd.is_dir():
        die(f"no such folder: {cwd}")
    extra = {"agent": a.agent, "title": alias} if a.kind == "opencode" else None
    return converse(a, alias, a.kind, None, cwd, a.access or "read", extra)


def cmd_send(a):
    entry = registry().get(a.alias)
    if not entry:
        die(f"no session named {a.alias}; see `relay.py names`")
    if entry.get("model") and not a.model and entry["kind"] != "opencode":
        a.model = entry["model"]
    if entry.get("effort") and not a.effort:
        a.effort = entry["effort"]
    # A session relay started keeps the access it started with; a registered one keeps its own settings.
    return converse(a, a.alias, entry["kind"], entry["session"], entry["cwd"], a.access or entry.get("access"))


def cmd_tell(a):
    to, sender = name_ok(a.to, "<to>"), sender_of(a)
    text = body_of(a)
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)[:20000]
    box = INBOX / to
    box.mkdir(parents=True, exist_ok=True)
    write_atomic(box / f"{stamp()}-{sender}.md", f"From: {sender}\nTime: {now()}\n\n{text}\n")
    log("told", sender, to, "inbox", text)
    print(f"Left the message in {to}'s inbox ({box}).")
    return 0


def take_mail(name, peek=False):
    box = INBOX / name
    mail = sorted(box.glob("*.md")) if box.exists() else []
    if not mail:
        return 0
    time.sleep(1)  # let a writer finish
    for f in mail:
        body = f.read_text(encoding="utf-8", errors="replace")
        print(f"=== {f.name}\n{body.strip()}\n---")
        if not peek:
            (box / "read").mkdir(exist_ok=True)
            shutil.move(str(f), str(box / "read" / f.name))
    return len(mail)


def cmd_inbox(a):
    n = take_mail(name_ok(a.name, "<name>"), a.peek)
    if not n:
        print(f"no mail for {a.name}")
    return 0 if n else 2


def cmd_watch(a):
    name, end = name_ok(a.name, "<name>"), time.time() + a.hours * 3600
    while time.time() < end:
        if take_mail(name):
            return 0
        time.sleep(a.every)
    print(f"no mail for {name} in {a.hours} h")
    return 2


# ---------- panel: several independent agents, from different labs, on one hard question

PANEL_R1 = """[agent-relay panel "{topic}", round 1 of {rounds}: independent analysis. You are Party {label}, one of {n} \
reviewers, each a different AI model. You will see the others' answers only in round 2, so give your own view and do \
not hedge toward a consensus.]

{brief}

Work read-only: read whatever code and documents you need, but change nothing. Answer in this structure:
1. Recommendation: what you would decide, in a few sentences.
2. Reasons: each tied to evidence you checked (file:line, command output, documentation). Mark anything you did not \
check as an assumption.
3. Pre-mortem: suppose your recommendation was adopted and failed expensively a year from now. Give the three likeliest \
causes.
4. What would change your mind: the observation or experiment that would make you decide differently.
5. Questions for the owner that your answer depends on."""

PANEL_RN = """[agent-relay panel "{topic}", round {r} of {rounds}: cross-examination. You are still Party {label}. Here \
are the other parties' latest answers, labelled by letter only.]

{others}

Answer in this structure:
1. Disagreements: for each other party, the claim you think is most wrong, and why. Check it against the code or \
documents where you can, and say whether you checked.
2. What they found that you missed.
3. Your position now: keep, change or narrow it, and say what moved you. Do not converge only to agree: a well-argued \
minority view is worth more than a weak consensus.
4. Open points: what only an experiment or the owner can settle, each with the cheapest test that would settle it."""

PANEL_MOD = """[agent-relay panel "{topic}": moderator. {n} independent AI reviewers (Parties {labels}) answered the \
brief below in {rounds} round(s). Do not add a design of your own and do not vote: report what the panel established. \
You may read the code and documents to check a disputed claim, but change nothing.]

=== Brief ===
{brief}

{transcript}

Write the synthesis:
1. Agreed: points every party holds, with the evidence behind them.
2. Disputed: each disagreement, the best argument on each side, and whose evidence is stronger (checked or assumed).
3. Single-source claims: important claims made by only one party, which must be verified before anyone relies on them.
4. Options: the realistic decisions, each with its main risk and its cost of reversal.
5. Next steps: the cheapest experiments to run before deciding, and the questions only the owner can answer."""

EFFORTS = ("low", "medium", "high", "xhigh", "max")


def parse_party(spec):
    kind, model, effort = (spec.split(":") + ["", ""])[:3]
    if kind not in KINDS:
        die(f"party {spec!r}: the kind must be one of {', '.join(KINDS)} (form kind[:model[:effort]])")
    if effort and effort not in EFFORTS:
        die(f"party {spec!r}: effort must be one of {', '.join(EFFORTS)}")
    return kind, model or None, effort or None


def panel_turn(p, text, timeout):
    """One party's turn, run in a worker thread. Read-only access always: a panel advises, it does not edit."""
    extra = {"title": p["alias"]} if p["kind"] == "opencode" and not p.get("sid") else {}
    code, sid, reply, stats, err = RUNNERS[p["kind"]](p["cwd"], deliverable(p["kind"], text), p.get("sid"), p["model"],
                                                      p["effort"], "read", timeout, **extra)
    p["sid"] = sid or p.get("sid")
    log("panel", p["sender"], p["alias"], f"{p['kind']} {p['sid']}", text, reply, stats)
    return code == 0 and bool((reply or "").strip()), (reply or "").strip(), stats, err


def cmd_panel(a):
    from concurrent.futures import ThreadPoolExecutor
    brief = Path(a.brief).read_text(encoding="utf-8").strip()
    if not brief:
        die("the brief is empty")
    topic = a.topic or short(next((l.strip("# ") for l in brief.splitlines() if l.strip()), "panel"), 80)
    specs = [parse_party(s) for s in a.party]
    if not 2 <= len(specs) <= 6:
        die("a panel takes 2 to 6 --party entries")
    cwd = Path(a.cwd).resolve()
    if not cwd.is_dir():
        die(f"no such folder: {cwd}")
    sender, tag = sender_of(a), f"panel{dt.datetime.now():%d%H%M%S}"
    ps = [{"label": "ABCDEF"[i], "kind": k, "model": m, "effort": e, "cwd": cwd, "alias": f"{tag}-{'ABCDEF'[i]}",
           "sender": sender, "answers": [], "ok": True} for i, (k, m, e) in enumerate(specs)]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", topic.lower()).strip("-")[:40] or "panel"
    out = Path(a.out).resolve() if a.out else HOME / "panels" / f"{tag}-{slug}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    who = "\n".join(f"- Party {p['label']}: {p['kind']} {p['model'] or '(default model)'}"
                    f"{' ' + p['effort'] if p['effort'] else ''}, alias {p['alias']}" for p in ps)
    doc = [f"# Panel: {topic}\n\nStarted {now()} by {sender}, in {cwd}. {a.rounds} round(s); parties work read-only "
           f"and see each other only by letter.\n\n{who}\n\n## Brief\n\n{brief}\n"]
    out.write_text("\n".join(doc), encoding="utf-8")
    for r in range(1, a.rounds + 1):
        live = [p for p in ps if p["ok"]]
        if len(live) < 2:
            print(f"relay: only {len(live)} party left; stopping before round {r}")
            break
        texts = {}
        for p in live:
            if r == 1:
                texts[p["label"]] = PANEL_R1.format(topic=topic, rounds=a.rounds, label=p["label"], n=len(ps), brief=brief)
            else:
                others = "\n\n".join(f"=== Party {q['label']} (round {r - 1}) ===\n{q['answers'][-1]}"
                                     for q in live if q is not p)
                texts[p["label"]] = PANEL_RN.format(topic=topic, r=r, rounds=a.rounds, label=p["label"], others=others)
        print(f"round {r}: {', '.join(p['label'] + '=' + p['kind'] for p in live)} ...", flush=True)
        with ThreadPoolExecutor(max_workers=len(live)) as pool:
            results = list(pool.map(lambda p: (p, panel_turn(p, texts[p["label"]], a.timeout)), live))
        section = [f"\n## Round {r}\n"]
        for p, (ok, reply, stats, err) in results:
            if ok:
                p["answers"].append(reply)
            else:
                p["ok"] = False
            section.append(f"### Party {p['label']} ({p['kind']} {p['model'] or ''}; {stats})\n\n"
                           f"{reply if ok else '(no answer: ' + short(err or reply or 'empty reply', 500) + ')'}\n")
            print(f"  Party {p['label']} ({p['kind']}): {'answered' if ok else 'FAILED'}; {stats}", flush=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(section))
    for p in ps:  # each party can be asked a follow-up later with `send <alias>`
        if p.get("sid"):
            remember(p["alias"], p["kind"], p["sid"], str(cwd), access="read", model=p["model"], effort=p["effort"])
    done = [p for p in ps if p["answers"]]
    if a.moderator and len(done) >= 2:
        k, m, e = parse_party(a.moderator)
        transcript = "\n\n".join(f"=== Party {p['label']}, round {i + 1} ===\n{ans}"
                                 for p in done for i, ans in enumerate(p["answers"]))
        mod = {"label": "M", "kind": k, "model": m, "effort": e, "cwd": cwd, "alias": f"{tag}-M", "sender": sender}
        print(f"moderator ({k}) ...", flush=True)
        ok, reply, stats, err = panel_turn(mod, PANEL_MOD.format(topic=topic, n=len(done), rounds=a.rounds,
                                                                 labels=", ".join(p["label"] for p in done),
                                                                 brief=brief, transcript=transcript), a.timeout)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(f"\n## Moderator synthesis ({k} {m or ''}; {stats})\n\n"
                     f"{reply if ok else '(failed: ' + short(err or 'empty reply', 500) + ')'}\n")
        if mod.get("sid"):
            remember(mod["alias"], k, mod["sid"], str(cwd), access="read", model=m, effort=e)
        print(f"  moderator: {'done' if ok else 'FAILED'}; {stats}")
    print(f"Transcript: {out}")
    print("Read it in full, check every claim you will rely on, and give the owner the decision with the evidence.")
    return 0 if len(done) >= 2 else 5


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="relay.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("whoami")
    r = sub.add_parser("register")
    r.add_argument("alias")
    r.add_argument("--kind", choices=KINDS)
    r.add_argument("--session")
    r.add_argument("--cwd")
    sub.add_parser("names")
    sub.add_parser("forget").add_argument("alias")
    for name in ("new", "send"):
        q = sub.add_parser(name)
        if name == "new":
            q.add_argument("kind", choices=KINDS)
            q.add_argument("--cwd", required=True)
            q.add_argument("--alias", required=True)
            q.add_argument("--agent", help="OpenCode: the agent to start with")
        else:
            q.add_argument("alias")
        q.add_argument("--from", dest="from_", help="your name, for the header and for replies by mail")
        q.add_argument("--access", choices=("read", "write", "full"),
                       help="what the agent may do (new: default read; send: what the session started with)")
        q.add_argument("--model")
        q.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"))
        q.add_argument("--timeout", type=float, help="minutes before giving up on the turn")
        q.add_argument("--wait", type=float, default=0, help="minutes to wait for a busy session")
        q.add_argument("--force", action="store_true", help="send even if the session looks busy or is open in a window")
        q.add_argument("--json", action="store_true", help="print the result as one JSON object")
        q.add_argument("--file")
        q.add_argument("message", nargs="*")
    t = sub.add_parser("tell")
    t.add_argument("to")
    t.add_argument("--from", dest="from_")
    t.add_argument("--file")
    t.add_argument("message", nargs="*")
    i = sub.add_parser("inbox")
    i.add_argument("name")
    i.add_argument("--peek", action="store_true")
    w = sub.add_parser("watch")
    w.add_argument("name")
    w.add_argument("--hours", type=float, default=8)
    w.add_argument("--every", type=float, default=15)
    pn = sub.add_parser("panel")
    pn.add_argument("--brief", required=True, help="file with the question and everything a newcomer needs")
    pn.add_argument("--cwd", required=True, help="the folder the parties may read (the repository)")
    pn.add_argument("--party", action="append", required=True, help="kind[:model[:effort]], given 2 to 6 times")
    pn.add_argument("--rounds", type=int, default=2, help="1 = blind answers only; 2+ adds cross-examination")
    pn.add_argument("--moderator", help="kind[:model[:effort]] of a fresh session that writes the synthesis")
    pn.add_argument("--topic")
    pn.add_argument("--timeout", type=float, default=30, help="minutes per turn")
    pn.add_argument("--out", help="transcript file (default ~/.agent-relay/panels/...)")
    pn.add_argument("--from", dest="from_")
    a = p.parse_args()
    handlers = {"doctor": cmd_doctor, "whoami": cmd_whoami, "register": cmd_register, "names": cmd_names,
                "forget": cmd_forget, "new": cmd_new, "send": cmd_send, "tell": cmd_tell, "inbox": cmd_inbox,
                "watch": cmd_watch, "panel": cmd_panel}
    return handlers[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
