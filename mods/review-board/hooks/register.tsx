import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Build, Run, RunSummary, Seat } from '../types'

// Live board and guardrails for pr-review-loop's /review-pr.
//
// The guardrails are the part that saves money: on a two-PR benchmark the
// reviewer seats ignored "batch your reads" and spent 17-51 turns each, one tool
// call per turn. A prompt asks; this refuses. Each seat gets a tool-call budget
// (reads of its own packet do not count), review seats may not run as
// general-purpose agents, and an optional guard blocks every posting command.

const PANE = 'review-board'
const run = atom({ plugin: 'review-board', key: 'run' } as const, null as Run | null)
const guard = atom({ plugin: 'review-board', key: 'guard' } as const, false)
const budget = atom({ plugin: 'review-board', key: 'budget' } as const, 15)
const history = atom({ plugin: 'review-board', key: 'history' } as const, [] as RunSummary[])

const REVIEW_CMD = /^\/(?:pr-review-loop:)?review-pr(?:\s|$)/
const SEAT_PROMPT = /You are Reviewer `?([A-F])`?/
const PR_URL = /https?:\/\/\S+?\/(?:pull|merge_requests)\/\d+/
const POSTING: RegExp[] = [
  /\bgh\s+pr\s+(?:comment|review|merge|close|edit|ready)\b/,
  /\bgh\s+api\b[^|;&]*(?:-X|--method)\s*(?:POST|PUT|PATCH|DELETE)\b/i,
  /\bgh\s+api\s+graphql\b[^|;&]*\bmutation\b/,
  /\bglab\s+mr\s+(?:note|approve|unapprove|merge|close|update)\b/,
  /\bglab\s+api\b[^|;&]*(?:-X|--method)\s*(?:POST|PUT|PATCH|DELETE)\b/i,
]
const POSTING_MCP = /^mcp__[^_]*gitlab[^_]*__(?:create_|update_|resolve_|delete_)/
const SEAT_NAMES: Record<string, string> = {
  A: 'architecture', B: 'correctness', C: 'perf / quality', E: 'seams', F: 'spec & ACs',
}

const field = (e: unknown, name: string): string => {
  const v = (e as Record<string, unknown>)[name]
  return typeof v === 'string' ? v : ''
}

const usd = async ($: EngineInterface) => (await $.session.usage()).cost?.usd ?? 0

const count = (text: string, sev: string) =>
  (text.match(new RegExp(`"severity"\\s*:\\s*"${sev}"`, 'g')) ?? []).length

const startRun = async ($: EngineInterface, args: string) => {
  const now = await $.clock.now()
  const next: Run = {
    pr: args.match(PR_URL)?.[0] ?? (args.trim().split(/\s+/)[0] || 'local diff'),
    mode: /--fork\b/.test(args) ? 'fork' : 'packet',
    startedAt: now, costAtStart: await usd($), cost: 0,
    seats: [], build: null, denied: 0, isFinished: false,
  }
  await update($, run, () => next)
  const { isPlaced } = await $.ui.open({ id: PANE, title: 'Review board' })
  if (!isPlaced) $.ui.status(statusText(next))
}

const statusText = (r: Run) => {
  const done = r.seats.filter(s => s.state !== 'reviewing').length
  const calls = r.seats.reduce((n, s) => n + s.calls, 0)
  const pr = r.pr.match(/(\d+)$/)?.[1]
  return `review ${pr ? '#' + pr : ''} · seats ${done}/${r.seats.length} · ${calls} calls · $${r.cost.toFixed(2)}`
}

const shortPr = (pr: string) => {
  const m = pr.match(/([^/]+)\/(?:pull|merge_requests)\/(\d+)$/)
  return m ? `${m[1]}#${m[2]}` : pr
}

const elapsed = (from: number, to: number) => {
  const s = Math.max(0, Math.round((to - from) / 1000))
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${String(s % 60).padStart(2, '0')}s`
}

let ticker: { cancel: () => void } | undefined

async function tick($: EngineInterface) {
  const r = await read($, run)
  if (!r || r.isFinished) {
    ticker?.cancel()
    ticker = undefined
    return
  }
  const cost = (await usd($)) - r.costAtStart
  let build = r.build
  if (build && build.state === 'running') {
    try {
      const rec = JSON.parse(await $.fs.read(build.path)) as {
        build?: { compiles?: boolean | null; analyzer_errors?: number; analyzer_warnings?: number;
                  pipeline?: string; ci_gates?: string[] }
        seconds?: number
      }
      const b = rec.build ?? {}
      build = { ...build, state: 'done', compiles: b.compiles, errors: b.analyzer_errors,
                warnings: b.analyzer_warnings, pipeline: b.pipeline, gates: b.ci_gates,
                seconds: rec.seconds }
    } catch {
      // not written yet: the gate is still running
    }
  }
  const nextRun = await update($, run, cur => (cur ? { ...cur, cost, build } : cur))
  if (nextRun) $.ui.status(statusText(nextRun))
}

function ensureTicker($: EngineInterface) {
  ticker ??= $.clock.every(4000, () => void tick($))
}


export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'review-board',
      description: 'Review board: open the pane, or `guard on|off`, `budget <n>`',
      argumentHint: '[guard on|off | budget <n>]',
    })
    return next(e)
  })

  on('command.run', { command: 'review-board' }, async ($, e) => {
    const [verb, value] = e.args.trim().split(/\s+/)
    if (verb === 'guard') {
      const on_ = value !== 'off'
      await update($, guard, () => on_)
      return { text: on_
        ? 'Posting guard on: gh/glab commands that comment, review, approve or merge are refused (dry run).'
        : 'Posting guard off.' }
    }
    if (verb === 'budget') {
      const n = Math.max(5, Math.min(60, Number(value) || 15))
      await update($, budget, () => n)
      return { text: `Seat tool-call budget set to ${n} (packet reads do not count).` }
    }
    await $.ui.open({ id: PANE, title: 'Review board' })
    return { text: 'Review board opened.' }
  })

  // a review starts: typed by the person, or run by the model / the watcher
  on('prompt.submit', async ($, e, next) => {
    if (REVIEW_CMD.test(e.text.trim())) {
      await startRun($, e.text.trim().replace(REVIEW_CMD, ''))
      ensureTicker($)
    }
    return next(e)
  })

  // review seats: refuse general-purpose, record the rest as they start
  on('agent.spawn', async ($, e, next) => {
    const seat = e.prompt.match(SEAT_PROMPT)?.[1]
    if (!seat) return next(e)
    if (e.subagentType === 'general-purpose') {
      return { deny: 'review-board: run review seats as `review-panel` agents (or forks with --fork), ' +
                     'not general-purpose — it re-sends ~100 unused tool schemas every turn.' }
    }
    const res = await next(e)
    if (res.deny === undefined && res.agentId) {
      const s: Seat = {
        agentId: res.agentId, label: seat, kind: e.subagentType, calls: 0, budgetHits: 0,
        state: 'reviewing', startedAt: await $.clock.now(), findings: 0, p0: 0, p1: 0, p2: 0,
      }
      let r = await read($, run)
      if (!r) {
        await startRun($, '')
        r = await read($, run)
      }
      await update($, run, cur => (cur ? { ...cur, seats: [...cur.seats, s] } : cur))
      ensureTicker($)
    }
    return res
  }).catch(($, e, next) => next(e))

  on('tool.call', async ($, e, next) => {
    // 1. posting guard (any loop)
    if (await read($, guard)) {
      const cmd = e.tool === 'Bash' ? field(e, 'command') : ''
      if ((cmd && POSTING.some(rx => rx.test(cmd))) || POSTING_MCP.test(e.tool)) {
        await update($, run, cur => (cur ? { ...cur, denied: cur.denied + 1 } : cur))
        return { deny: 'review-board guard is on: posting to GitHub/GitLab is refused (dry run). ' +
                       'Write the overview and findings to a local file instead. `/review-board guard off` to allow.' }
      }
    }

    // 2. a review started by the model or the watcher, not typed
    if (e.tool === 'Skill' && /(?:^|:)review-pr$/.test(field(e, 'skill'))) {
      await startRun($, field(e, 'args'))
      ensureTicker($)
    }

    // 3. the build gate's output file, so the pane can follow it
    if (e.tool === 'Bash') {
      const out = field(e, 'command').match(/build-gate\.py[^\n]*--out\s+(\S+)/)?.[1]
      if (out) {
        const b: Build = { path: out.replace(/^['"]|['"]$/g, ''), state: 'running' }
        await update($, run, cur => (cur ? { ...cur, build: b } : cur))
      }
    }

    // 4. seat budget
    if (e.agentId) {
      const r = await read($, run)
      const seat = r?.seats.find(s => s.agentId === e.agentId)
      if (seat) {
        const isPacketRead = e.tool === 'Read' && /\/packets\/(?:common-\d+|seat-[A-F])\.md$/.test(field(e, 'file_path'))
        const limit = await read($, budget)
        if (!isPacketRead && seat.calls >= limit) {
          await update($, run, cur => cur && {
            ...cur,
            seats: cur.seats.map(s => (s.agentId === seat.agentId ? { ...s, budgetHits: s.budgetHits + 1 } : s)),
          })
          return { deny: `review-board: Reviewer ${seat.label} has used its ${limit} tool calls. ` +
                         'Stop reading and return your findings JSON now with what you have.' }
        }
        if (!isPacketRead) {
          await update($, run, cur => cur && {
            ...cur,
            seats: cur.seats.map(s => (s.agentId === seat.agentId ? { ...s, calls: s.calls + 1 } : s)),
          })
        }
      }
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  // a seat hands back; the main loop's turn ending closes the run
  on('turn.complete', async ($, e, next) => {
    const r = await read($, run)
    if (r && !r.isFinished) {
      const now = await $.clock.now()
      if (e.agentId && r.seats.some(s => s.agentId === e.agentId)) {
        const text = e.answer ?? ''
        await update($, run, cur => cur && {
          ...cur,
          seats: cur.seats.map(s => (s.agentId === e.agentId ? {
            ...s, state: e.isAborted ? 'stopped' : 'done', endedAt: now,
            findings: count(text, 'P[012]'), p0: count(text, 'P0'), p1: count(text, 'P1'), p2: count(text, 'P2'),
          } : s)),
        })
      } else if (!e.agentId && r.seats.length > 0 && r.seats.every(s => s.state !== 'reviewing')) {
        await tick($)
        const done = await update($, run, cur => cur && { ...cur, isFinished: true, endedAt: now })
        if (done) {
          const sum: RunSummary = {
            pr: done.pr, mode: done.mode, minutes: Math.round((now - done.startedAt) / 6000) / 10,
            cost: Math.round(done.cost * 100) / 100,
            findings: done.seats.reduce((n, s) => n + s.findings, 0),
            p0: done.seats.reduce((n, s) => n + s.p0, 0), p1: done.seats.reduce((n, s) => n + s.p1, 0),
            denied: done.denied, at: now,
          }
          await update($, history, list => [sum, ...list].slice(0, 20))
          await $.store.set('history', await read($, history))
          $.ui.status(undefined)
          $.ui.toast(`Review ${shortPr(done.pr)}: ${sum.findings} raw findings (P0 ${sum.p0}, P1 ${sum.p1}) · ` +
                     `$${sum.cost.toFixed(2)} · ${sum.minutes} min`)
        }
      }
    }
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const r = await read($, run)
    const isGuarded = await read($, guard)
    const limit = await read($, budget)
    const past = await read($, history)
    const now = await $.clock.now()

    const header = (
      <Text dimColor>
        guard {isGuarded ? 'ON (dry run)' : 'off'} · seat budget {limit} calls
      </Text>
    )
    if (!r) {
      return (
        <Box flexDirection="column">
          {header}
          <Text dimColor>No review yet. Run /review-pr &lt;url&gt; [--fork].</Text>
          {past.length > 0 && <Text bold>Recent</Text>}
          {past.slice(0, 8).map(h => (
            <Text dimColor>
              {shortPr(h.pr)} · {h.mode} · {h.minutes} min · ${h.cost.toFixed(2)} · P0 {h.p0} P1 {h.p1}
            </Text>
          ))}
        </Box>
      )
    }

    const b = r.build
    const buildLine = !b ? 'not started'
      : b.state === 'running' ? 'running…'
      : `${b.compiles === true ? 'compiles' : b.compiles === false ? 'BROKEN' : 'unverified'}` +
        ` · analyzer ${b.errors ?? 0} err / ${b.warnings ?? 0} warn · pipeline ${b.pipeline ?? 'n/a'}` +
        (b.seconds ? ` · ${Math.round(b.seconds / 60)} min` : '')
    const totals = r.seats.reduce((t, s) => ({ f: t.f + s.findings, p0: t.p0 + s.p0, p1: t.p1 + s.p1 }),
                                  { f: 0, p0: 0, p1: 0 })

    return (
      <Box flexDirection="column">
        <Text bold>
          {shortPr(r.pr)} · {r.mode} mode · {elapsed(r.startedAt, r.endedAt ?? now)} · ${r.cost.toFixed(2)}
          {r.isFinished ? ' · done' : ''}
        </Text>
        {header}
        <Text> </Text>
        {r.seats.length === 0 && <Text dimColor>Building packets / waiting for seats…</Text>}
        {r.seats.map(s => (
          <Text color={s.state === 'reviewing' ? undefined : s.state === 'done' ? 'success' : 'warning'}>
            {s.label} {(SEAT_NAMES[s.label] ?? '').padEnd(15)}{' '}
            {s.state === 'reviewing' ? 'reviewing ' : s.state === 'done' ? 'done      ' : 'stopped   '}
            {String(s.calls).padStart(2)}/{limit} calls
            {s.budgetHits > 0 ? ` (+${s.budgetHits} refused)` : ''}
            {s.state !== 'reviewing' ? ` · ${s.findings} findings` : ''}
            {' · '}{elapsed(s.startedAt, s.endedAt ?? now)}
          </Text>
        ))}
        <Text>D build-gate      {buildLine}</Text>
        <Text> </Text>
        <Text>
          raw findings {totals.f} · P0 {totals.p0} · P1 {totals.p1}
          {r.denied > 0 ? ` · ${r.denied} posting call(s) refused` : ''}
        </Text>
      </Box>
    )
  })
}
