# Protocol notes for relay testing

## Endpoint map

Given `base` (e.g. `https://relay.example`), the script normalizes it to a root by stripping `/v1`, `/v1/models`, `/v1/messages`, `/v1/chat/completions`, `/v1/responses` and trailing slashes. Then:

| Purpose | URL |
|---|---|
| Model list | `{root}/v1/models` |
| Anthropic Messages (Claude Code) | `{root}/v1/messages` |
| OpenAI Chat Completions | `{root}/v1/chat/completions` |
| OpenAI Responses (Codex) | `{root}/v1/responses` |

Claude Code's `ANTHROPIC_BASE_URL` must be the **root**, not `.../v1`; Claude Code appends `/v1/messages` itself.

Codex's `base_url` in `config.toml` should be `{root}/v1` with `wire_api = "responses"`.

## Auth

- Anthropic-style clients usually send `Authorization: Bearer <key>` when configured with `ANTHROPIC_AUTH_TOKEN`.
- `ANTHROPIC_API_KEY` sends `x-api-key` instead.
- New API relays often accept only `Authorization: Bearer` on `/v1/models` and reject `x-api-key` with `未提供令牌`.
- The script tries Bearer first, then `x-api-key`, for the model list.

## Claude Code probing

Claude Code is the only trustworthy test for Claude models on relays that fingerprint clients. Details that matter:

- Find the newest binary under `~/.local/share/claude/versions/` (numeric sort), else `shutil.which("claude")`.
- Run: `claude -p "Reply with exactly: OK" --model <model> --output-format json`.
- Clear inherited `ANTHROPIC_*` and `CLAUDE_CODE_*` variables first, especially:
  `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`,
  `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL`,
  `ANTHROPIC_SMALL_FAST_MODEL`.
- Set all of them again to the target model/base; otherwise Claude Code may mix the new base URL with an old model name.
- Working responses on a busy free relay took ~38–42 seconds. Use a 90-second timeout. Timeout usually means the relay is retrying 503s, not that the model is slow.
- Claude Code validates model names: `claude-*` custom names are accepted; `gpt-6-astra-cc-format` produces `unrecognized_model` and never sends the request.

## Codex probing

Codex uses the OpenAI Responses API. A minimal compatible body:

```json
{
  "model": "gpt-6.1-sol",
  "input": [
    {"role": "user", "content": [{"type": "input_text", "text": "Reply with exactly: OK"}]}
  ],
  "prompt_cache_key": "relay-api-check",
  "store": false,
  "stream": true,
  "reasoning": {"effort": "low"}
}
```

Lessons:

- `input` must be an **array of messages**. Some relays return `input is required` for a bare string even though the official API accepts it.
- Some relays require `prompt_cache_key`; omit it and you get `prompt_cache_key is required`.
- `reasoning` and `text.verbosity` are accepted by newer models; if a relay rejects them, retry without.
- `/v1/chat/completions` often returns `404 当前 API 不支持所选模型` for models that work fine on `/v1/responses`. Do not conclude the model is dead from a chat-completions 404.
- `gpt-6-astra` may return `500 当前模型 ... 负载已经达到上限`（`get_channel_failed`）— upstream saturated, not an auth failure.
- `gpt-5-codex` can be listed but rejected with `当前 API 不支持所选模型`; always test, don't trust the name.
- Codex refreshes `/v1/models` expecting a `models` field, while New API relays return `data`. Codex then logs `failed to refresh available models` and `Model metadata for ... not found`. This is noisy but non-fatal; the model still answers.
- `codex --profile NAME` layers `$CODEX_HOME/NAME.config.toml` on top of `config.toml` (Codex CLI 0.154+), which is a clean way to keep a relay profile separate from the default config.

## Status codes

| Code / message | Usual meaning |
|---|---|
| 401 `未提供令牌` | header style wrong; try the other auth header |
| 404 `当前 API 不支持所选模型` | model not in the key's group, or not routed on this protocol |
| 429 `Service Unavailable` | rate limit / no channel; retry later or another model |
| 500 `负载已经达到上限` | upstream saturated |
| 503 `Service Unavailable` | no available channel; may still work through a real client |
| 400 `input is required` | wrong Responses body shape |
| 400 `prompt_cache_key is required` | add the cache key |
| 400 `not implemented ... convert_request_error` | relay cannot translate this protocol for that model |

## Billing sanity check

`GET {root}/v1/dashboard/billing/usage` with Bearer returns a `total_usage` number. If it increases after tests, requests really reached the relay rather than being served by the local Claude Code subscription. The script does not currently query this, but it is useful for manual confirmation.

## Model list caveat

`/v1/models` is usually the relay's global catalog, not the key's entitlement. A 17-model list may have only 3 working models. Always test.

## Safety

- Test prompt is constant and contains no user data.
- Keys are stored only in `~/.claude/relay-keys.env` (chmod 600) and redacted in reports.
- `--all` can take 15+ minutes; announce it before running.