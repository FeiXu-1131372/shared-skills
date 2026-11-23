import type { AgentInfo, Register } from 'claude-code'

// rich-agent-rows: one row per subagent, in fixed-width columns so the dividers line up:
//   opus 5.5 · high    │ 39m40s │ ↓ 344.1k │  58 tok/s │ Task · what it is doing now
// The task and activity go last, so a narrow terminal cuts them, not the numbers.

const ESC = '\u001b['
const DIM = `${ESC}2m`
const RESET = `${ESC}0m`
const SEP = ` ${DIM}│${RESET} `

const MODEL_WIDTH = 18 // "sonnet 5.5 · high", "haiku 5.5 · medium"
const ELAPSED_WIDTH = 6 // "39m40s", " 3m05s", " 2h34m"
const TOKENS_WIDTH = 6 // "344.1k", "  1.2M"
const RATE_WIDTH = 4 // "  58", "1204"

// Generation speed comes from each model request of the agent: output tokens
// over the time from the first streamed piece to the end, the last few requests
// pooled so one short tool-call reply does not swing it.
type Step = { tokens: number; ms: number }
const STEPS_KEPT = 3
const MIN_STEP_MS = 300
const steps = new Map<string, Step[]>()

export function ramp(percent: number): string {
  const p = Math.max(0, Math.min(100, percent))
  const [r, g] = p <= 50 ? [Math.round((p / 50) * 255), 255] : [255, Math.round(((100 - p) / 50) * 255)]
  return `${ESC}38;2;${r};${g};0m`
}

export function modelName(id: string | undefined): string {
  if (!id) return ''
  return id
    .replace(/^claude-/, '')
    .replace(/\[.*\]$/, '')
    .replace(/-(\d+)-(\d+)$/, ' $1.$2')
    .replace(/-/, ' ')
}

export function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  if (s >= 3600) return `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`
  if (s >= 60) return `${Math.floor(s / 60)}m${String(s % 60).padStart(2, '0')}s`
  return `${s}s`
}

export function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

export function rateOf(agentId: string): number | undefined {
  const kept = steps.get(agentId)
  if (!kept || kept.length === 0) return undefined
  const tokens = kept.reduce((n, s) => n + s.tokens, 0)
  const ms = kept.reduce((n, s) => n + s.ms, 0)
  return ms > 0 ? Math.round((tokens / ms) * 1000) : undefined
}

export function recordStep(agentId: string, tokens: number, ms: number): void {
  if (tokens <= 0 || ms < MIN_STEP_MS) return
  const kept = steps.get(agentId) ?? []
  kept.push({ tokens, ms })
  if (kept.length > STEPS_KEPT) kept.shift()
  steps.delete(agentId) // re-insert so the map keeps the newest last
  steps.set(agentId, kept)
  if (steps.size > 200) steps.delete(steps.keys().next().value as string)
}

type RowInput = Pick<AgentInfo, 'type' | 'description' | 'label' | 'startTime' | 'model' | 'effort' | 'tokenCount' | 'lastRequest'>

export function formatRow(a: RowInput, now: number, rate: number | undefined): string {
  const effort = a.lastRequest?.effort ?? a.effort
  const model = modelName(a.lastRequest?.model ?? a.model)
  const modelCell = (effort !== undefined && model ? `${model} · ${effort}` : model).padEnd(MODEL_WIDTH)

  const elapsedMs = now - a.startTime
  const elapsedCell = `${ramp(elapsedMs / 36_000)}${formatElapsed(elapsedMs).padStart(ELAPSED_WIDTH)}${RESET}`

  const tokensCell = `↓ ${formatCount(a.tokenCount).padStart(TOKENS_WIDTH)}`

  const rateCell =
    rate !== undefined && rate > 0
      ? `${String(rate).padStart(RATE_WIDTH)} tok/s`
      : `${DIM}${'–'.padStart(RATE_WIDTH)} tok/s${RESET}`

  const kind = a.type && a.type !== 'general-purpose' ? `${a.type}: ` : ''
  const activity = (a.label ?? '').split('\n')[0]?.trim() ?? ''
  const task = `${kind}${a.description}${activity && activity !== a.description ? ` ${DIM}· ${activity}${RESET}` : ''}`

  return [modelCell, elapsedCell, tokensCell, rateCell, task].join(SEP)
}

export const register: Register = on => {
  on('turn.step', async function* ($, e, next) {
    const stream = next(e)
    if (!e.agentId) return yield* stream

    let first: number | undefined
    for await (const chunk of stream) {
      if (first === undefined) first = await $.clock.now()
      yield chunk
    }
    const result = await stream.result
    const out = result.usage?.output_tokens ?? 0
    if (first !== undefined) recordStep(e.agentId, out, (await $.clock.now()) - first)
    return result
  })

  on('ui.render', { component: 'AgentRow' }, async ($, e, next) => {
    const now = await $.clock.now()
    const body = formatRow(e.props, now, rateOf(e.props.id))
    return next({ ...e, props: { ...e.props, body } })
  })
}
