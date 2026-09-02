/**
 * Component-level labeling flow test.
 *
 * Spec 03 sec 10 asks for a scripted Playwright session timed in CI. This is the component half of
 * the substitution recorded as **D-004** in PLAN.md: Playwright downloads browsers at test time,
 * which contradicts the tool's hard offline requirement. The API half lives in
 * `tests/test_labeling_session.py`.
 *
 * What is verified here is the part only a rendered UI can show: that a keystroke produces the
 * right request, and that committing advances to the next unlabeled run.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LabelerPage } from '../pages/LabelerPage'
import type { RunDetail, Stats } from '../types'

function makeRun(id: string, overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    run_id: id,
    source: 'otel',
    started: '2026-08-15T09:15:00+00:00',
    duration: 6480,
    input: `Investigate unmatched transaction for ${id}`,
    outcome: { status: 'success', output: 'Root cause: partial payment.', error: null },
    meta: { n_steps: 2 },
    steps: [
      {
        kind: 'llm',
        name: 'gpt-4o-mini',
        args_preview: 'system: You are a reconciliation analyst',
        output_preview: 'assistant: I need the open invoices',
        latency: 1620,
        error: null,
        args: { messages: [{ role: 'user', content: 'the full prompt payload' }] },
        output: 'the full completion payload',
      },
      {
        kind: 'tool',
        name: 'search_counterparty',
        args_preview: '{"name":"ORBITAL LOGISTICS LTD"}',
        output_preview: '{"counterparty_id":"CP-4471"}',
        latency: 230,
        error: null,
        args: { name: 'ORBITAL LOGISTICS LTD' },
        output: { counterparty_id: 'CP-4471' },
      },
    ],
    verdict: null,
    tags: [],
    note: '',
    seconds_spent: null,
    ...overrides,
  }
}

const emptyStats: Stats = {
  runs_total: 2,
  runs_by_source: { otel: 2 },
  runs_labeled: 0,
  runs_unlabeled: 2,
  runs_with_error: 0,
  labeled_fraction: 0,
  verdicts: { right: 0, wrong: 0, partial: 0 },
  failure_tags: {},
  labels_timed: 0,
  median_seconds_per_label: null,
  mean_seconds_per_label: null,
  fastest_seconds: null,
  slowest_seconds: null,
  session_labels: 0,
  session_median_seconds: null,
  target_median_seconds: 10,
  meets_speed_target: null,
  cases_total: 0,
  cases_by_version: {},
  export_versions: [],
}

/** Captures the label requests the UI actually sends. */
let labelCalls: { runId: string; body: Record<string, unknown> }[] = []

function installFetchStub() {
  labelCalls = []
  const fetchStub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()

    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })

    if (url.startsWith('/api/stats')) return json(emptyStats)

    const labelMatch = url.match(/^\/api\/runs\/([^/]+)\/label$/)
    if (labelMatch && init?.method === 'POST') {
      const runId = decodeURIComponent(labelMatch[1] as string)
      labelCalls.push({ runId, body: JSON.parse(String(init.body)) })
      return json({
        run_id: runId,
        verdict: 'wrong',
        tags: [],
        next_run_id: runId === 'run-one' ? 'run-two' : null,
        runs_unlabeled: runId === 'run-one' ? 1 : 0,
      })
    }

    if (url.startsWith('/api/runs/next-unlabeled')) return json(makeRun('run-one'))

    const detailMatch = url.match(/^\/api\/runs\/([^/?]+)$/)
    if (detailMatch) return json(makeRun(decodeURIComponent(detailMatch[1] as string)))

    throw new Error(`unstubbed request: ${url}`)
  })

  vi.stubGlobal('fetch', fetchStub)
  return fetchStub
}

function renderLabeler(initialPath = '/label/run-one') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/label" element={<LabelerPage />} />
          <Route path="/label/:runId" element={<LabelerPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('labeling flow', () => {
  beforeEach(() => {
    installFetchStub()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the trace timeline with a card per step', async () => {
    renderLabeler()

    expect(await screen.findByText('gpt-4o-mini')).toBeInTheDocument()
    expect(screen.getByText('search_counterparty')).toBeInTheDocument()
    expect(screen.getByText(/Investigate unmatched transaction/)).toBeInTheDocument()
    // Latency is rendered in human units, not raw milliseconds.
    expect(screen.getByText('1.62s')).toBeInTheDocument()
    expect(screen.getByText('230ms')).toBeInTheDocument()
  })

  it('commits a verdict from the keyboard alone', async () => {
    const user = userEvent.setup()
    renderLabeler()
    await screen.findByText('gpt-4o-mini')

    // W = wrong, 1 = wrong_tool, 2 = bad_args, Enter = commit.
    await user.keyboard('w12{Enter}')

    await waitFor(() => expect(labelCalls).toHaveLength(1))
    expect(labelCalls[0]?.runId).toBe('run-one')
    expect(labelCalls[0]?.body.verdict).toBe('wrong')
    expect(labelCalls[0]?.body.tags).toEqual(['wrong_tool', 'bad_args'])
  })

  it('sends a measured seconds_spent so the median is real data', async () => {
    const user = userEvent.setup()
    renderLabeler()
    await screen.findByText('gpt-4o-mini')

    await user.keyboard('r{Enter}')

    await waitFor(() => expect(labelCalls).toHaveLength(1))
    const seconds = labelCalls[0]?.body.seconds_spent
    expect(typeof seconds).toBe('number')
    expect(seconds as number).toBeGreaterThanOrEqual(0)
  })

  it('auto-advances to the next unlabeled run after committing', async () => {
    const user = userEvent.setup()
    renderLabeler()
    await screen.findByText(/Investigate unmatched transaction for run-one/)

    await user.keyboard('r{Enter}')

    // The next run's detail replaces the current one without any further user action.
    expect(
      await screen.findByText(/Investigate unmatched transaction for run-two/),
    ).toBeInTheDocument()
  })

  it('toggles a verdict button state so mouse users see the same thing', async () => {
    const user = userEvent.setup()
    renderLabeler()
    await screen.findByText('gpt-4o-mini')

    const wrong = screen.getByRole('button', { name: /^W Wrong$/ })
    expect(wrong).toHaveAttribute('aria-pressed', 'false')

    await user.keyboard('w')
    expect(wrong).toHaveAttribute('aria-pressed', 'true')
  })

  it('toggles a failure tag off when its digit is pressed twice', async () => {
    const user = userEvent.setup()
    renderLabeler()
    await screen.findByText('gpt-4o-mini')

    const tagButton = screen.getByRole('button', { name: /^1 Wrong tool$/ })
    await user.keyboard('w1')
    expect(tagButton).toHaveAttribute('aria-pressed', 'true')

    await user.keyboard('1')
    expect(tagButton).toHaveAttribute('aria-pressed', 'false')
  })

  it('expands a step payload with X', async () => {
    const user = userEvent.setup()
    renderLabeler()
    await screen.findByText('gpt-4o-mini')

    expect(screen.queryByText(/the full completion payload/)).not.toBeInTheDocument()

    await user.keyboard('x')

    expect(await screen.findByText(/the full completion payload/)).toBeInTheDocument()
  })

  it('moves the step cursor with J and K', async () => {
    const user = userEvent.setup()
    renderLabeler()
    await screen.findByText('gpt-4o-mini')

    await user.keyboard('jj')
    await user.keyboard('x')

    // The cursor stops at the last step, so the second step's payload is what opens.
    expect(await screen.findByText(/"counterparty_id": "CP-4471"/)).toBeInTheDocument()
  })

  it('does not fire verdicts while the note field has focus', async () => {
    const user = userEvent.setup()
    renderLabeler()
    await screen.findByText('gpt-4o-mini')

    await user.keyboard('n')
    const note = screen.getByLabelText('Note')
    expect(note).toHaveFocus()

    // "wrong" contains w, r and p: none may register as a verdict while typing.
    await user.keyboard('wrong reference')
    expect(note).toHaveValue('wrong reference')
    expect(screen.getByRole('button', { name: /^W Wrong$/ })).toHaveAttribute('aria-pressed', 'false')
  })

  it('refuses to commit without a verdict', async () => {
    const user = userEvent.setup()
    renderLabeler()
    await screen.findByText('gpt-4o-mini')

    await user.keyboard('{Enter}')

    expect(labelCalls).toHaveLength(0)
    expect(screen.getByRole('button', { name: /Commit/ })).toBeDisabled()
  })

  it('requires a note when the "other" tag is used', async () => {
    const user = userEvent.setup()
    renderLabeler()
    await screen.findByText('gpt-4o-mini')

    await user.keyboard('w7{Enter}')
    expect(labelCalls).toHaveLength(0)

    await user.keyboard('it escalated to the wrong queue')
    await user.click(screen.getByRole('button', { name: /Commit/ }))

    await waitFor(() => expect(labelCalls).toHaveLength(1))
    expect(labelCalls[0]?.body.note).toBe('it escalated to the wrong queue')
    expect(labelCalls[0]?.body.tags).toEqual(['other'])
  })

  it('shows the keyboard legend and a help panel on ?', async () => {
    const user = userEvent.setup()
    renderLabeler()
    await screen.findByText('gpt-4o-mini')

    // The legend is always visible, not hidden behind a menu.
    expect(screen.getByText(/verdict ·/)).toBeInTheDocument()

    await user.keyboard('?')
    const help = await screen.findByText('Keyboard reference')
    expect(help).toBeInTheDocument()
    expect(
      within(help.closest('section') as HTMLElement).getByText(/commit and advance/),
    ).toBeInTheDocument()
  })

  it('shows live session stats including the median', async () => {
    const user = userEvent.setup()
    renderLabeler()
    await screen.findByText('gpt-4o-mini')

    expect(screen.getByText('Labeled this session')).toBeInTheDocument()
    expect(screen.getByText('Median / label')).toBeInTheDocument()

    await user.keyboard('r{Enter}')
    await waitFor(() => expect(labelCalls).toHaveLength(1))

    // After one label the session counter has moved off zero.
    await waitFor(() => {
      const tile = screen.getByText('Labeled this session').parentElement as HTMLElement
      expect(within(tile).getByText('1')).toBeInTheDocument()
    })
  })
})
