---
name: relay-api-check
description: 测试第三方 LLM 中转站 / API key / base URL / endpoint 的连通性和真实模型可用性，并把 endpoint+key 存进本地 `~/.claude/relay-keys.env` 供下次直接复用。Use whenever the user pastes a relay URL, an `sk-...` key, or an Anthropic/OpenAI-compatible endpoint and asks "这个能用吗", "测一下", "有哪些模型", "能不能接 Claude Code", "能不能接 Codex", "model availability", "test this API key", or asks to check/save/list third-party API credentials. Also use when a relay returns 503/429/404 and the user wants to know whether the relay or the model is broken. 也用于比较两个中转站、给某个 key 做体检、找出哪个模型真的能跑。
---

# Relay API Check

给第三方中转站做一次完整体检：认证方式、模型列表、Anthropic / OpenAI 两种协议、以及**真实客户端**（Claude Code、Codex 的 Responses API）能不能跑通。结果写一份 md 报告，endpoint 和 key 存进本地 env 登记表。

## 为什么不能只看 curl

中转站经常按客户端做限制：直连 `curl /v1/messages` 可能全部 503，而 Claude Code 发同样请求能成功。模型列表也常常是全局的，不代表这个 key 能用。

所以判定顺序是：

1. `/v1/models` —— 认证和模型清单
2. `curl /v1/messages` —— 只作参考
3. **Claude Code 实测** —— Claude 模型能不能用的唯一标准
4. **Responses API 实测** —— Codex 能不能用的标准

报告里会把这几层分开写，不要把 curl 的 503 当成最终结论。

## 快速开始

用户给了 URL + key：

```bash
python3 ~/.claude/skills/relay-api-check/scripts/relay_check.py probe \
  --base "https://relay.example" \
  --key "sk-..." \
  --name relay-example \
  --save
```

用户只给了 key（`sk-...`）：

- 直接跑，脚本会按 key 去登记表里匹配 base：
  ```bash
  python3 ~/.claude/skills/relay-api-check/scripts/relay_check.py probe --key "sk-..."
  ```
- 匹配不到会报“需要 --base”，这时再问用户 URL。不要猜域名，也不要把 key 发到任何在线服务去反查。

用户说"测一下上次那个"：

```bash
python3 ~/.claude/skills/relay-api-check/scripts/relay_check.py probe --name <NAME>
```

默认就是快速模式（最多 6 个最值得测的模型，可用 `--max-models` 调整）。要全测用 `--all`，会慢很多。

## 命令

```bash
# 只看模型列表，不测
relay_check.py models --name NAME

# 体检（默认最多 6 个最值得测的模型）
relay_check.py probe --base URL --key KEY --name NAME [--save]

# 指定模型
relay_check.py probe --name NAME --models claude-opus-5-5,gpt-6.1-sol

# 全量（每个模型最多 90 秒，可能十几分钟）
relay_check.py probe --name NAME --all --timeout 90

# 只测 HTTP，不启 Claude Code 子进程
relay_check.py probe --name NAME --raw-only

# 登记表
relay_check.py save --name NAME --base URL --key KEY [--note "..."]
relay_check.py list
relay_check.py show NAME      # key 只显示前后几位
relay_check.py remove NAME
```

报告写到 `~/.claude/relay-reports/<name>-YYYYMMDD-HHMM.md`，同时打印到终端。

## 输出怎么读

- `✅` = 真实客户端实测通过
- `⚠️` = HTTP 层有响应但客户端没通过（比如 curl 503 但 Claude Code 能过，会归到 ✅；反之为 ⚠️）
- `❌` = 超时 / 4xx / 5xx / 模型被客户端拒绝

报告末尾会给两段可直接用的配置：Claude Code 的 env，和 Codex 的 `config.toml`。

## 环境变量的坑

这台机器上可能已经有 `ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`ANTHROPIC_DEFAULT_*_MODEL` 指向别的服务（例如别的服务商的模型名）。只改 base URL 会让 Claude Code 拿着旧的模型名去问新中转，报 `unrecognized_model`。

脚本在启动 Claude Code 子进程时会**清掉所有相关变量再按本次测试重设**，所以它测的是目标中转，不是你当前的默认配置。手工测试时要记得这一点。

Claude Code 只接受 `claude-*` 形状的自定义模型名；`gpt-6-astra-cc-format` 这类名字会被判 `unrecognized_model`，不要用它测 Claude Code。

## Key 的存放

- 登记表：`~/.claude/relay-keys.env`，权限 `600`，格式是 `NAME_BASE_URL=` / `NAME_KEY=`，可以直接 `source`。
- 报告：`~/.claude/relay-reports/`，key 只写 `sk-abc…xyz` 这种脱敏形式。
- 不要把 key 写进项目目录、git、或聊天回复的正文里；用户自己贴过来的除外。
- 用户如果不想留，跑 `remove NAME`。

## 常见故障

| 现象 | 含义 |
|---|---|
| `/v1/models` 401，Bearer 失败但 x-api-key 成功 | 用 `x-api-key` 风格；报告会写 auth 方式 |
| 所有 Claude 模型 curl 503，但 Claude Code 通过 | 中转站按客户端限制，正常，按 Claude Code 结果算可用 |
| `404 当前 API 不支持所选模型` | key 的分组没有这个模型，或该协议不路由它 |
| `500 当前模型 ... 负载已经达到上限` | 上游满载，过一会再试，不代表 key 坏了 |
| `429 Service Unavailable` | 限流/无可用渠道；换模型或等 |
| `input is required`（Responses） | 有些中转只认数组形式的 `input`；脚本已经用数组 |
| `prompt_cache_key is required` | 这个中转要求 Responses 请求带缓存键；脚本已带 |
| Claude Code 超时无输出 | 多半在重试 503；该模型当前不可用 |

## 测试原则

- 测试 prompt 固定为 `Reply with exactly: OK`，不发送用户的项目内容。
- 一次只测一个模型，串行；中转站通常经不起并发。
- 默认 90 秒/模型；Claude Code 正常约 40 秒，超过 90 秒基本就是不可用。
- 不安装任何东西；只调用本机已有的 `claude` 二进制和 HTTP。
- `--all` 之前先告诉用户大概要多久。

更多协议细节见 `references/protocols.md`。