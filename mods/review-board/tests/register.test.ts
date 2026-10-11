import { expect, test } from 'claude-code/testing'
import type { On } from 'claude-code'

// The engine beneath the plugin: a spawned seat gets an id, every tool call
// succeeds, and the session reports a cost.
function engine(on: On) {
  on('agent.spawn', () => ({ model: 'claude-opus-5-5', agentId: 'seat-a' }))
  on('tool.call', () => ({ result: { text: 'ok' } }) as never)
  on('clock.now', () => ({ value: 1_000 }) as never)
  on('session.usage', () => ({ value: { startedAt: 0, context: {}, rateLimits: [], cost: { usd: 1.5 } } }) as never)
  on('ui.open', () => ({ value: { isPlaced: false } }) as never)
  on('ui.status', () => ({ value: undefined }) as never)
  on('clock.every', () => ({ value: undefined }) as never)
}

const spawn = (prompt: string, subagentType: string) => ({
  tool_use_id: `t-${subagentType}`, prompt, description: 'Reviewer A architecture',
  subagentType, provider: { plugin: 'engine', tier: 'core' },
}) as never

const call = (tool: string, input: Record<string, unknown>, agentId?: string) =>
  ({ tool, tool_use_id: `c-${Math.random()}`, ...input, ...(agentId ? { agentId } : {}) }) as never

test('a review seat may not run as general-purpose', async ($, on) => {
  engine(on)
  const res = await $.agent.spawn(spawn('You are Reviewer `A`. Read the packet.', 'general-purpose'))
  expect((res as { deny?: string }).deny).toMatch(/review-panel/)
})

test('other agents spawn untouched', async ($, on) => {
  engine(on)
  const res = await $.agent.spawn(spawn('Summarize the README.', 'general-purpose'))
  expect((res as { agentId?: string }).agentId).toBe('seat-a')
})

test('a seat is refused after its budget; packet reads do not count', async ($, on) => {
  engine(on)
  await $.agent.spawn(spawn('You are Reviewer `B`. Read the packet.', 'review-panel'))
  for (let i = 1; i <= 7; i++) {
    const r = await $.tool.call(call('Read', { file_path: `/s/packets/common-0${i}.md` }, 'seat-a'))
    expect((r as { deny?: string }).deny).toBeUndefined()
  }
  for (let i = 0; i < 15; i++) {
    const r = await $.tool.call(call('Bash', { command: `git show HEAD:f${i}` }, 'seat-a'))
    expect((r as { deny?: string }).deny).toBeUndefined()
  }
  const over = await $.tool.call(call('Bash', { command: 'git show HEAD:f15' }, 'seat-a'))
  expect((over as { deny?: string }).deny).toMatch(/Reviewer B has used its 15 tool calls/)
  // the main loop is never budgeted
  const main = await $.tool.call(call('Bash', { command: 'git status' }))
  expect((main as { deny?: string }).deny).toBeUndefined()
})

test('the posting guard refuses gh/glab writes only while on', async ($, on) => {
  engine(on)
  const post = call('Bash', { command: 'gh pr comment 12 --repo o/r --body "x"' })
  expect((await $.tool.call(post) as { deny?: string }).deny).toBeUndefined()

  await $.command.run({ command: 'review-board', args: 'guard on', origin: { kind: 'user' } } as never)
  expect((await $.tool.call(post) as { deny?: string }).deny).toMatch(/guard is on/)
  const approve = call('Bash', { command: 'glab api -X POST "projects/1/merge_requests/2/approve"' })
  expect((await $.tool.call(approve) as { deny?: string }).deny).toMatch(/guard is on/)
  const read = call('Bash', { command: 'gh pr view 12 --json title' })
  expect((await $.tool.call(read) as { deny?: string }).deny).toBeUndefined()

  await $.command.run({ command: 'review-board', args: 'guard off', origin: { kind: 'user' } } as never)
  expect((await $.tool.call(post) as { deny?: string }).deny).toBeUndefined()
})
