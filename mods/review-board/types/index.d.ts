export type SeatState = 'reviewing' | 'done' | 'stopped'

export type Seat = {
  agentId: string
  label: string
  kind: string
  calls: number
  budgetHits: number
  state: SeatState
  startedAt: number
  endedAt?: number
  findings: number
  p0: number
  p1: number
  p2: number
}

export type Build = {
  path: string
  state: 'running' | 'done'
  compiles?: boolean | null
  errors?: number
  warnings?: number
  pipeline?: string
  gates?: string[]
  seconds?: number
}

export type Run = {
  pr: string
  mode: 'auto' | 'packet' | 'fork'
  startedAt: number
  costAtStart: number
  cost: number
  seats: Seat[]
  build: Build | null
  denied: number
  isFinished: boolean
  endedAt?: number
}

export type RunSummary = {
  pr: string
  mode: 'auto' | 'packet' | 'fork'
  minutes: number
  cost: number
  findings: number
  p0: number
  p1: number
  denied: number
  at: number
}

declare module 'claude-code' {
  interface PluginState {
    'review-board': {
      run: Run | null
      guard: boolean
      budget: number
      history: RunSummary[]
    }
  }
}
