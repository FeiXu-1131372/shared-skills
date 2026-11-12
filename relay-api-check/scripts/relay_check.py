#!/usr/bin/env python3
"""Probe a third-party LLM relay: models, auth, Claude Code, Codex.

Local-only. The registry lives in ~/.claude/relay-keys.env (chmod 600).
Reports are written to ~/.claude/relay-reports/.

Examples:
  relay_check.py probe --base https://relay.example --key sk-xxx --save --name example
  relay_check.py probe --name example --quick
  relay_check.py list
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

REGISTRY = Path.home() / ".claude" / "relay-keys.env"
REPORTS = Path.home() / ".claude" / "relay-reports"
PROMPT = "Reply with exactly: OK"

ANTHROPIC_DROP = [
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_PID",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_CHILD_SESSION",
]


# ---------------------------------------------------------------- utilities


def root_url(base: str) -> str:
    """Return the host root (no /v1, /v1/messages, trailing slash)."""
    b = base.strip().rstrip("/")
    for suffix in ("/v1/messages", "/v1/chat/completions", "/v1/responses", "/v1/models", "/v1"):
        if b.endswith(suffix):
            b = b[: -len(suffix)]
            break
    return b.rstrip("/")


def redact(key: str) -> str:
    if not key:
        return "(none)"
    if len(key) <= 10:
        return "***"
    return f"{key[:6]}…{key[-4:]}"


def sanitize_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return n or "RELAY"


def http_json(url: str, headers: dict, body: dict | None = None, timeout: float = 30):
    data = None
    hdrs = dict(headers)
    if body is not None:
        data = json.dumps(body).encode()
        hdrs.setdefault("content-type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data else "GET")
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return {
                "ok": True,
                "status": r.status,
                "body": raw,
                "text": raw.decode("utf-8", "replace"),
                "seconds": round(time.time() - started, 1),
            }
    except urllib.error.HTTPError as e:
        raw = e.read()
        return {
            "ok": False,
            "status": e.code,
            "body": raw,
            "text": raw.decode("utf-8", "replace"),
            "seconds": round(time.time() - started, 1),
        }
    except Exception as e:  # timeout, DNS, TLS...
        return {
            "ok": False,
            "status": None,
            "body": b"",
            "text": f"{type(e).__name__}: {e}",
            "seconds": round(time.time() - started, 1),
        }


def short(text: str, n: int = 160) -> str:
    text = " ".join(text.split())
    return text[:n] + ("…" if len(text) > n else "")


# ---------------------------------------------------------------- registry


def load_registry() -> dict:
    entries: dict[str, dict] = {}
    if not REGISTRY.exists():
        return entries
    for line in REGISTRY.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        m = re.match(r"^([A-Z0-9_]+)_(BASE_URL|KEY|NOTE)$", k)
        if not m:
            continue
        name = m.group(1)
        field = {"BASE_URL": "base", "KEY": "key", "NOTE": "note"}[m.group(2)]
        entries.setdefault(name, {})[field] = v
    return entries


def save_registry(entries: dict) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Local relay registry — created by relay-api-check.",
        "# chmod 600. Never commit or paste this file into a chat.",
        "",
    ]
    for name in sorted(entries):
        e = entries[name]
        if e.get("base"):
            lines.append(f"{name}_BASE_URL={e['base']}")
        if e.get("key"):
            lines.append(f"{name}_KEY={e['key']}")
        if e.get("note"):
            lines.append(f"{name}_NOTE={e['note']}")
        lines.append("")
    REGISTRY.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(REGISTRY, 0o600)


def resolve_entry(args) -> tuple[str, str, str, str]:
    raw_name = (getattr(args, "name", "") or "").strip()
    name = sanitize_name(raw_name) if raw_name else ""
    base = (getattr(args, "base", "") or "").strip()
    key = (getattr(args, "key", "") or "").strip()
    note = (getattr(args, "note", "") or "").strip()
    entries = load_registry()
    if name and name in entries:
        base = base or entries[name].get("base", "")
        key = key or entries[name].get("key", "")
        note = note or entries[name].get("note", "")
    if key and not name:
        # If only a key is given, try to match it against the registry.
        for n, e in entries.items():
            if e.get("key") == key:
                name = n
                base = base or e.get("base", "")
                break
    if not base:
        raise SystemExit("需要 --base（或先用 save 存过的 --name）")
    if not key:
        raise SystemExit("需要 --key（或先用 save 存过的 --name）")
    if not name:
        name = sanitize_name(urllib.parse.urlsplit(base).hostname or "relay")
    return name, base, key, note


# ---------------------------------------------------------------- probes


def list_models(base: str, key: str) -> dict:
    url = root_url(base) + "/v1/models"
    tried = []
    last_error = ""

    for label, headers in (
        ("Authorization: Bearer", {"Authorization": f"Bearer {key}"}),
        ("x-api-key", {"x-api-key": key, "anthropic-version": "2023-06-01"}),
    ):
        r = http_json(url, headers, timeout=30)
        tried.append({"auth": label, "status": r["status"], "ok": r["ok"]})
        if r["status"] is None:
            last_error = r["text"]
        if r["ok"]:
            try:
                data = json.loads(r["text"])
                models = [m["id"] for m in data.get("data", []) if "id" in m]
            except Exception:
                models = []
            if models:
                return {"ok": True, "auth": label, "models": models, "tried": tried, "text": r["text"]}
    return {"ok": False, "auth": None, "models": [], "tried": tried, "text": last_error}


def anthropic_raw(base: str, key: str, model: str, timeout: float = 45) -> dict:
    url = root_url(base) + "/v1/messages"
    body = {
        "model": model,
        "max_tokens": 16,
        "messages": [{"role": "user", "content": PROMPT}],
    }
    r = http_json(
        url,
        {
            "Authorization": f"Bearer {key}",
            "anthropic-version": "2023-06-01",
        },
        body,
        timeout=timeout,
    )
    text = ""
    if r["ok"]:
        try:
            d = json.loads(r["text"])
            text = "".join(
                c.get("text", "") for c in d.get("content", []) if c.get("type") == "text"
            )
        except Exception:
            pass
    return {"kind": "anthropic_raw", "status": r["status"], "ok": r["ok"], "seconds": r["seconds"], "reply": text, "raw": short(r["text"])}


def responses_probe(base: str, key: str, model: str, timeout: float = 90, stream: bool = False) -> dict:
    url = root_url(base) + "/v1/responses"
    body = {
        "model": model,
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": PROMPT}]}
        ],
        "prompt_cache_key": "relay-api-check",
        "store": False,
        "stream": stream,
        "reasoning": {"effort": "low"},
    }
    if not stream:
        r = http_json(url, {"Authorization": f"Bearer {key}"}, body, timeout=timeout)
        text = ""
        if r["ok"]:
            try:
                d = json.loads(r["text"])
                for item in d.get("output", []):
                    for c in item.get("content", []):
                        if c.get("type") == "output_text":
                            text += c.get("text", "")
            except Exception:
                pass
        return {"kind": "responses", "status": r["status"], "ok": r["ok"], "seconds": r["seconds"], "reply": text, "raw": short(r["text"]), "stream": False}

    # Streaming check: read until response.completed or output_text appears.
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json", "accept": "text/event-stream"},
        method="POST",
    )
    started = time.time()
    buf = b""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            while time.time() - started < timeout:
                chunk = resp.read(512)
                if not chunk:
                    break
                buf += chunk
                if b"response.completed" in buf or b"output_text" in buf:
                    break
        text = buf.decode("utf-8", "replace")
        completed = b"response.completed" in buf or b"output_text" in buf
        failed = b"response.failed" in buf or b"event: error" in buf
        ok = completed and not failed
        return {"kind": "responses", "status": 200, "ok": ok, "seconds": round(time.time() - started, 1), "reply": "stream OK" if ok else ("stream failed" if failed else "no completion event"), "raw": short(text), "stream": True}
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        return {"kind": "responses", "status": e.code, "ok": False, "seconds": round(time.time() - started, 1), "reply": "", "raw": short(text), "stream": True}
    except Exception as e:
        return {"kind": "responses", "status": None, "ok": False, "seconds": round(time.time() - started, 1), "reply": "", "raw": f"{type(e).__name__}: {e}", "stream": True}


def chat_probe(base: str, key: str, model: str, timeout: float = 60) -> dict:
    url = root_url(base) + "/v1/chat/completions"
    body = {"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": PROMPT}]}
    r = http_json(url, {"Authorization": f"Bearer {key}"}, body, timeout=timeout)
    text = ""
    if r["ok"]:
        try:
            d = json.loads(r["text"])
            text = d.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception:
            pass
    return {"kind": "chat", "status": r["status"], "ok": r["ok"], "seconds": r["seconds"], "reply": text, "raw": short(r["text"])}


def find_claude_bin() -> str | None:
    versions = Path.home() / ".local" / "share" / "claude" / "versions"
    if versions.is_dir():
        cands = []
        for p in versions.iterdir():
            if p.is_file() and re.match(r"^\d+\.\d+\.\d+$", p.name):
                cands.append(p)
        if cands:
            cands.sort(key=lambda p: tuple(int(x) for x in p.name.split(".")), reverse=True)
            return str(cands[0])
    return shutil.which("claude")


def claude_code_probe(base: str, key: str, model: str, timeout: float = 90) -> dict:
    binary = find_claude_bin()
    if not binary:
        return {"kind": "claude_code", "status": None, "ok": False, "seconds": 0, "reply": "", "raw": "claude binary not found"}

    env = {k: v for k, v in os.environ.items() if k not in ANTHROPIC_DROP}
    env.update(
        {
            "ANTHROPIC_BASE_URL": root_url(base),
            "ANTHROPIC_AUTH_TOKEN": key,
            "ANTHROPIC_MODEL": model,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
            "ANTHROPIC_SMALL_FAST_MODEL": model,
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
    )
    cmd = [binary, "-p", PROMPT, "--model", model, "--output-format", "json"]
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            env=env,
            cwd="/tmp",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"kind": "claude_code", "status": None, "ok": False, "seconds": round(time.time() - started, 1), "reply": "", "raw": f"timeout after {timeout:.0f}s"}

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    reply = ""
    cost = None
    usage = None
    try:
        d = json.loads(stdout.splitlines()[-1])
        reply = d.get("result") or ""
        cost = d.get("total_cost_usd")
        usage = d.get("usage")
    except Exception:
        pass
    ok = proc.returncode == 0 and reply.strip().upper().startswith("OK")
    raw = stderr or short(stdout)
    if "unrecognized_model" in raw:
        raw = "model rejected by Claude Code: " + short(raw, 120)
    return {"kind": "claude_code", "status": 200 if ok else None, "ok": ok, "seconds": round(time.time() - started, 1), "reply": short(reply, 80), "raw": short(raw, 180), "cost": cost, "usage": usage}


# ---------------------------------------------------------------- selection


def model_score(mid: str) -> int:
    s = 0
    if "claude-opus-5-5" in mid:
        s += 100
    elif "fable-5" in mid:
        s += 95
    elif "opus-5" in mid:
        s += 90
    elif "sonnet-5" in mid:
        s += 85
    elif "haiku-5" in mid:
        s += 80
    elif mid.startswith("claude-opus-4-7"):
        s += 70
    elif mid.startswith("claude-opus-4-6"):
        s += 65
    elif mid.startswith("claude-opus-4"):
        s += 60
    elif mid.startswith("claude-sonnet-4"):
        s += 55
    elif mid.startswith("claude-3"):
        s += 20
    elif "gpt-6.1" in mid:
        s += 75
    elif "gpt-6" in mid:
        s += 70
    elif "gpt-5" in mid:
        s += 50
    elif "gemini" in mid:
        s += 40
    return s


def select_models(models: list[str], args) -> list[str]:
    if args.models:
        wanted = [m.strip() for m in args.models.split(",") if m.strip()]
        return [m for m in wanted if m in models] + [m for m in wanted if m not in models]
    ordered = sorted(models, key=lambda m: (-model_score(m), m))
    if args.all:
        return ordered
    return ordered[: max(1, args.max_models)]


def family(mid: str) -> str:
    if mid.startswith("claude"):
        return "claude"
    if mid.startswith(("gpt-", "o1", "o3", "o4")):
        return "gpt"
    if "gemini" in mid:
        return "gemini"
    return "other"


# ---------------------------------------------------------------- report


def summarize(results: list[dict]) -> dict:
    claude = [r for r in results if family(r["model"]) == "claude"]
    gpt = [r for r in results if family(r["model"]) == "gpt"]
    return {
        "claude_tested": bool(claude),
        "gpt_tested": bool(gpt),
        "claude_ok": [r["model"] for r in claude if r.get("client_ok")],
        "gpt_ok": [r["model"] for r in gpt if r.get("client_ok")],
        "dead": [r["model"] for r in results if not r.get("client_ok")],
    }


def build_report(name: str, base: str, key: str, models_info: dict, results: list[dict], started: datetime) -> str:
    s = summarize(results)
    lines = [
        f"# Relay check: {name}",
        "",
        f"- Base: `{root_url(base)}`",
        f"- Key: `{redact(key)}`",
        f"- Time: {started.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Models endpoint: {'OK' if models_info.get('ok') else 'FAILED'}"
        f" ({len(models_info.get('models', []))} models, auth: {models_info.get('auth') or 'unknown'})",
        "",
        "## Model matrix",
        "",
        "| Model | Probe | Status | Time | Evidence |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        probe = {"claude_code": "Claude Code", "anthropic_raw": "curl /v1/messages", "responses": "Responses API", "chat": "chat/completions"}.get(r["probe"], r["probe"])
        status = "✅" if r.get("client_ok") else ("⚠️" if r.get("raw_ok") else "❌")
        evidence = (r.get("reply") or r.get("raw") or "").replace("|", "\\|")
        lines.append(f"| `{r['model']}` | {probe} | {status} | {r.get('seconds', '')}s | {short(evidence, 100)} |")

    lines += ["", "## Verdict", ""]
    if not s["claude_tested"]:
        lines.append("- Claude Code: — 本次没有测试 Claude 模型")
    elif s["claude_ok"]:
        lines.append(f"- Claude Code: ✅ 可用 — `{s['claude_ok'][0]}`")
    else:
        lines.append("- Claude Code: ❌ 没有实测通过的 Claude 模型")
    if not s["gpt_tested"]:
        lines.append("- Codex / Responses API: — 本次没有测试 GPT 模型")
    elif s["gpt_ok"]:
        lines.append(f"- Codex / Responses API: ✅ 可用 — `{s['gpt_ok'][0]}`")
    else:
        lines.append("- Codex / Responses API: ❌ 没有实测通过的 GPT 模型")
    if s["dead"]:
        lines.append(f"- 不可用/超时: {', '.join('`' + m + '`' for m in s['dead'])}")

    lines += ["", "## Config snippets", ""]
    if s["claude_ok"]:
        best = s["claude_ok"][0]
        lines += [
            "Claude Code（注意同时覆盖所有 `ANTHROPIC_*_MODEL`，否则会沿用你环境里已有的默认模型）:",
            "",
            "```",
            f'export ANTHROPIC_BASE_URL="{root_url(base)}"',
            f'export ANTHROPIC_AUTH_TOKEN="{redact(key)}"  # 用真实 key 替换',
            f'export ANTHROPIC_MODEL="{best}"',
            f'export ANTHROPIC_DEFAULT_OPUS_MODEL="{best}"',
            f'export ANTHROPIC_DEFAULT_SONNET_MODEL="{best}"',
            f'export ANTHROPIC_DEFAULT_HAIKU_MODEL="{best}"',
            f'export ANTHROPIC_SMALL_FAST_MODEL="{best}"',
            "```",
            "",
        ]
    if s["gpt_ok"]:
        best = s["gpt_ok"][0]
        lines += [
            "Codex（`~/.codex/config.toml`）:",
            "",
            "```",
            f'model = "{best}"',
            'model_provider = "relay"',
            "",
            "[model_providers.relay]",
            f'base_url = "{root_url(base)}/v1"',
            'env_key = "RELAY_API_KEY"',
            'wire_api = "responses"',
            "```",
            "",
            "```",
            'export RELAY_API_KEY="<真实 key>"',
            "codex",
            "```",
            "",
        ]

    lines += [
        "## Notes",
        "",
        "- 模型列表是全局的，不代表你的 key 能用；以实测为准。",
        "- 直连 curl 可能被中转站拦成 503，而 Claude Code 客户端能通；Claude 模型一律以 Claude Code 实测为准。",
        "- Codex 走 `/v1/responses`；`/v1/chat/completions` 对很多模型是 404。",
        "- Key 只在本地使用；`--save` 时写入 `~/.claude/relay-keys.env`（chmod 600），不要提交到任何仓库。",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- commands


def cmd_probe(args) -> int:
    name, base, key, note = resolve_entry(args)
    started = datetime.now()

    print(f"→ {name}  {root_url(base)}  key={redact(key)}", file=sys.stderr)
    models_info = list_models(base, key)
    if not models_info["ok"]:
        print("✗ /v1/models 不可用。尝试过的认证方式：", file=sys.stderr)
        for t in models_info["tried"]:
            print(f"  - {t['auth']}: HTTP {t['status']}", file=sys.stderr)
        if models_info.get("text"):
            print(f"  error: {models_info['text']}", file=sys.stderr)
        return 2

    models = models_info["models"]
    if not models:
        print("✗ /v1/models 返回空列表（认证可能有效，但这个 key 没有可用模型）", file=sys.stderr)
        return 3
    print(f"✓ {len(models)} models via {models_info['auth']}", file=sys.stderr)
    selected = select_models(models, args)
    print(f"→ testing: {', '.join(selected)}", file=sys.stderr)

    results = []
    for i, model in enumerate(selected, 1):
        fam = family(model)
        print(f"[{i}/{len(selected)}] {model} …", file=sys.stderr)
        entry = {"model": model, "client_ok": False, "raw_ok": False}

        if fam == "claude":
            raw = anthropic_raw(base, key, model, timeout=min(args.timeout, 45))
            entry.update({"probe": "anthropic_raw", "status": raw["status"], "seconds": raw["seconds"], "reply": raw["reply"], "raw": raw["raw"]})
            entry["raw_ok"] = raw["ok"]
            print(f"    curl: HTTP {raw['status']} {short(raw['raw'], 80)}", file=sys.stderr)
            if not args.raw_only:
                cc = claude_code_probe(base, key, model, timeout=args.timeout)
                entry.update({"probe": "claude_code", "status": cc["status"], "seconds": cc["seconds"], "reply": cc["reply"], "raw": cc["raw"], "cost": cc.get("cost")})
                entry["client_ok"] = cc["ok"]
                print(f"    claude: {'OK' if cc['ok'] else 'FAIL'} ({cc['seconds']}s) {short(cc['raw'], 100)}", file=sys.stderr)
            else:
                entry["client_ok"] = raw["ok"]
        elif fam == "gpt":
            if not args.raw_only:
                rs = responses_probe(base, key, model, timeout=args.timeout, stream=True)
                entry.update({"probe": "responses", "status": rs["status"], "seconds": rs["seconds"], "reply": rs["reply"], "raw": rs["raw"]})
                entry["client_ok"] = rs["ok"]
                if not rs["ok"]:
                    rs2 = responses_probe(base, key, model, timeout=args.timeout, stream=False)
                    if rs2["ok"]:
                        entry.update({"status": rs2["status"], "seconds": rs2["seconds"], "reply": rs2["reply"]})
                        entry["client_ok"] = True
                    entry["raw"] = short(rs["raw"] + " | non-stream: " + rs2["raw"], 200)
                print(f"    responses: {'OK' if rs['ok'] else 'FAIL'} (HTTP {rs['status']}, {rs['seconds']}s) {short(rs['raw'], 100)}", file=sys.stderr)
            else:
                ch = chat_probe(base, key, model, timeout=args.timeout)
                entry.update({"probe": "chat", "status": ch["status"], "seconds": ch["seconds"], "reply": ch["reply"], "raw": ch["raw"]})
                entry["client_ok"] = ch["ok"]
                print(f"    chat: {'OK' if ch['ok'] else 'FAIL'} (HTTP {ch['status']})", file=sys.stderr)
        else:
            ch = chat_probe(base, key, model, timeout=args.timeout)
            entry.update({"probe": "chat", "status": ch["status"], "seconds": ch["seconds"], "reply": ch["reply"], "raw": ch["raw"]})
            entry["client_ok"] = ch["ok"]
            if not ch["ok"]:
                rs = responses_probe(base, key, model, timeout=args.timeout)
                if rs["ok"]:
                    entry.update({"probe": "responses", "status": rs["status"], "seconds": rs["seconds"], "reply": rs["reply"], "raw": rs["raw"]})
                    entry["client_ok"] = True
            print(f"    {entry['probe']}: {'OK' if entry['client_ok'] else 'FAIL'} {short(entry.get('raw',''), 100)}", file=sys.stderr)
        results.append(entry)

    report = build_report(name, base, key, models_info, results, started)
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{sanitize_name(name).lower()}-{started.strftime('%Y%m%d-%H%M')}.md"
    path.write_text(report, encoding="utf-8")

    if args.save:
        entries = load_registry()
        entries[sanitize_name(name)] = {"base": root_url(base), "key": key, "note": note}
        save_registry(entries)
        print(f"✓ saved to {REGISTRY}", file=sys.stderr)

    if args.json:
        print(json.dumps({"name": name, "base": root_url(base), "models": models, "results": results, "verdict": summarize(results)}, ensure_ascii=False, indent=2))
    else:
        print(report)
    print(f"\n(report: {path})", file=sys.stderr)
    return 0


def cmd_models(args) -> int:
    name, base, key, _ = resolve_entry(args)
    info = list_models(base, key)
    if not info["ok"]:
        print("✗ /v1/models 不可用。尝试过的认证方式：", file=sys.stderr)
        for t in info["tried"]:
            print(f"  - {t['auth']}: HTTP {t['status']}", file=sys.stderr)
        if info.get("text"):
            print(f"  error: {info['text']}", file=sys.stderr)
        return 2
    print(f"# {name} — {len(info['models'])} models via {info['auth']}")
    for m in info["models"]:
        print(m)
    return 0


def cmd_save(args) -> int:
    name = sanitize_name(args.name or "")
    if not name or not args.base or not args.key:
        raise SystemExit("save 需要 --name --base --key")
    entries = load_registry()
    entries[name] = {"base": root_url(args.base), "key": args.key, "note": args.note or ""}
    save_registry(entries)
    print(f"saved {name}: {root_url(args.base)}  key={redact(args.key)}")
    return 0


def cmd_list(args) -> int:
    entries = load_registry()
    if not entries:
        print(f"(empty: {REGISTRY})")
        return 0
    for name, e in sorted(entries.items()):
        print(f"{name:20} {e.get('base',''):45} {redact(e.get('key',''))}  {e.get('note','')}")
    return 0


def cmd_show(args) -> int:
    entries = load_registry()
    name = sanitize_name(args.name)
    e = entries.get(name)
    if not e:
        raise SystemExit(f"no entry: {name}")
    print(f"name: {name}\nbase: {e.get('base')}\nkey:  {redact(e.get('key',''))}\nnote: {e.get('note','')}")
    return 0


def cmd_remove(args) -> int:
    entries = load_registry()
    name = sanitize_name(args.name)
    if name not in entries:
        raise SystemExit(f"no entry: {name}")
    del entries[name]
    save_registry(entries)
    print(f"removed {name}")
    return 0


# ---------------------------------------------------------------- main


def main() -> int:
    p = argparse.ArgumentParser(description="Probe third-party LLM relays.")
    sub = p.add_subparsers(dest="cmd")

    probe = sub.add_parser("probe", help="list models and test real connectivity")
    probe.add_argument("--name", help="registry name (reuse saved base/key)")
    probe.add_argument("--base", "--url", dest="base", help="base URL, e.g. https://relay.example")
    probe.add_argument("--key", "--token", dest="key", help="API key")
    probe.add_argument("--note", default="", help="free-form note")
    probe.add_argument("--models", help="comma-separated model IDs")
    probe.add_argument("--all", action="store_true", help="test every model (slow)")
    probe.add_argument("--max-models", type=int, default=6, help="default number to test (default 6)")
    probe.add_argument("--timeout", type=float, default=90, help="per-client probe timeout seconds")
    probe.add_argument("--raw-only", action="store_true", help="skip Claude Code / Responses real-client probes")
    probe.add_argument("--save", action="store_true", help="save endpoint+key to the registry")
    probe.add_argument("--json", action="store_true", help="print JSON instead of markdown")
    probe.set_defaults(func=cmd_probe)

    models = sub.add_parser("models", help="just list /v1/models")
    models.add_argument("--name", help="registry name (reuse saved base/key)")
    models.add_argument("--base", "--url", dest="base", help="base URL")
    models.add_argument("--key", "--token", dest="key", help="API key")
    models.add_argument("--note", default="")
    models.set_defaults(func=cmd_models)

    save = sub.add_parser("save", help="save endpoint+key locally")
    save.add_argument("--name", required=True)
    save.add_argument("--base", "--url", dest="base", required=True)
    save.add_argument("--key", "--token", dest="key", required=True)
    save.add_argument("--note", default="")
    save.set_defaults(func=cmd_save)

    ls = sub.add_parser("list", help="list saved relays")
    ls.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="show one saved relay (key redacted)")
    show.add_argument("name")
    show.set_defaults(func=cmd_show)

    rm = sub.add_parser("remove", help="remove a saved relay")
    rm.add_argument("name")
    rm.set_defaults(func=cmd_remove)

    args = p.parse_args()
    if not getattr(args, "cmd", None):
        p.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())