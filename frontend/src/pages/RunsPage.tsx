import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api'
import { Card, ConfidencePill, EmptyState, RiskTag, StatBadge } from '../components/aurora'
import type { RunFilters, Source } from '../types'

/** All four filters spec 03 F3 names: source, has-error, duration, unlabeled-first. */
const DURATION_PRESETS = [
  { label: 'Any duration', min: null, max: null },
  { label: 'Under 2s', min: null, max: 2000 },
  { label: '2s – 6s', min: 2000, max: 6000 },
  { label: 'Over 6s', min: 6000, max: null },
]

function formatDuration(ms: number | null): string {
  if (ms === null) return '—'
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}

export function RunsPage() {
  const [source, setSource] = useState<Source | ''>('')
  const [errorOnly, setErrorOnly] = useState(false)
  const [durationIndex, setDurationIndex] = useState(0)
  const [unlabeledFirst, setUnlabeledFirst] = useState(true)
  const [labeled, setLabeled] = useState<'' | 'yes' | 'no'>('')

  const preset = DURATION_PRESETS[durationIndex] ?? DURATION_PRESETS[0]!

  const filters: RunFilters & { limit: number } = {
    source: source || undefined,
    has_error: errorOnly ? true : undefined,
    min_duration_ms: preset.min ?? undefined,
    max_duration_ms: preset.max ?? undefined,
    labeled: labeled === '' ? undefined : labeled === 'yes',
    unlabeled_first: unlabeledFirst,
    limit: 500,
  }

  const runsQuery = useQuery({
    queryKey: ['runs', filters],
    queryFn: () => api.listRuns(filters),
  })

  const stats = useQuery({ queryKey: ['stats'], queryFn: api.getStats })
  const runs = runsQuery.data ?? []

  const selectClass =
    'rounded-lg border border-white/10 bg-navy-900/80 px-2.5 py-1.5 text-sm text-slate-200'

  return (
    <div className="space-y-4">
      <Card
        padded={false}
        title="Runs"
        subtitle={`${runs.length} shown`}
        actions={
          <>
            <StatBadge
              label="unlabeled"
              value={stats.data?.runs_unlabeled ?? '—'}
              tone={stats.data?.runs_unlabeled ? 'amber' : 'emerald'}
            />
            <StatBadge label="total" value={stats.data?.runs_total ?? '—'} />
            <Link
              to="/label"
              className="rounded-lg border border-emerald-500/50 bg-emerald-500/20 px-3 py-1.5 text-sm font-semibold text-emerald-200"
            >
              Start labeling
            </Link>
          </>
        }
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-5 py-3">
          <select
            aria-label="Filter by source"
            value={source}
            onChange={(event) => setSource(event.target.value as Source | '')}
            className={selectClass}
          >
            <option value="">All sources</option>
            <option value="otel">OpenTelemetry</option>
            <option value="langsmith">LangSmith</option>
          </select>

          <select
            aria-label="Filter by duration"
            value={durationIndex}
            onChange={(event) => setDurationIndex(Number(event.target.value))}
            className={selectClass}
          >
            {DURATION_PRESETS.map((option, index) => (
              <option key={option.label} value={index}>
                {option.label}
              </option>
            ))}
          </select>

          <select
            aria-label="Filter by label state"
            value={labeled}
            onChange={(event) => setLabeled(event.target.value as '' | 'yes' | 'no')}
            className={selectClass}
          >
            <option value="">Labeled &amp; unlabeled</option>
            <option value="no">Unlabeled only</option>
            <option value="yes">Labeled only</option>
          </select>

          <label className="inline-flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={errorOnly}
              onChange={(event) => setErrorOnly(event.target.checked)}
              className="accent-emerald-500"
            />
            Has error
          </label>

          <label className="inline-flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={unlabeledFirst}
              onChange={(event) => setUnlabeledFirst(event.target.checked)}
              className="accent-emerald-500"
            />
            Unlabeled first
          </label>
        </div>

        {runsQuery.isLoading ? (
          <p className="px-5 py-10 text-center text-sm text-slate-500">Loading runs…</p>
        ) : runs.length === 0 ? (
          <EmptyState title="No runs match these filters">
            Clear a filter, or import more traces on the Import screen.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-white/10 text-[0.7rem] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-5 py-2 font-medium">Verdict</th>
                  <th className="px-3 py-2 font-medium">Input</th>
                  <th className="px-3 py-2 font-medium">Source</th>
                  <th className="px-3 py-2 text-right font-medium">Steps</th>
                  <th className="px-3 py-2 text-right font-medium">Took</th>
                  <th className="px-3 py-2 font-medium">Tags</th>
                  <th className="px-5 py-2" />
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.run_id} className="border-b border-white/5 hover:bg-white/[0.03]">
                    <td className="px-5 py-2.5">
                      <ConfidencePill verdict={run.verdict} />
                    </td>
                    <td className="max-w-md px-3 py-2.5">
                      <div className="truncate text-slate-200">{run.input_preview || '(no input)'}</div>
                      <div className="truncate font-mono text-[0.7rem] text-slate-500">
                        {run.run_id.slice(0, 20)}
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className="font-mono text-xs text-slate-400">{run.source}</span>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-slate-300">
                      {run.n_steps}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-slate-300">
                      {formatDuration(run.duration)}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {run.has_error && (
                          <span className="rounded-md border border-rose-500/30 bg-rose-500/10 px-1.5 py-0.5 text-[0.7rem] text-rose-200">
                            error
                          </span>
                        )}
                        {run.tags.map((tag) => (
                          <RiskTag key={tag} tag={tag} />
                        ))}
                      </div>
                    </td>
                    <td className="px-5 py-2.5 text-right">
                      <Link
                        to={`/label/${encodeURIComponent(run.run_id)}`}
                        className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-slate-200 hover:bg-white/10"
                      >
                        {run.verdict ? 'Relabel' : 'Label'}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
