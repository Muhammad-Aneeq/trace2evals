import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api } from './api'
import { StatBadge } from './components/aurora'
import { CasesPage } from './pages/CasesPage'
import { ExportPage } from './pages/ExportPage'
import { ImportPage } from './pages/ImportPage'
import { LabelerPage } from './pages/LabelerPage'
import { RunsPage } from './pages/RunsPage'

const NAV = [
  { to: '/import', label: 'Import' },
  { to: '/runs', label: 'Runs' },
  { to: '/label', label: 'Label' },
  { to: '/cases', label: 'Cases' },
  { to: '/export', label: 'Export' },
]

export function App() {
  // Polled rather than pushed: one small query keeps the header honest without a websocket.
  const stats = useQuery({ queryKey: ['stats'], queryFn: api.getStats })

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-5 px-4 py-5 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <h1 className="font-display text-xl font-semibold tracking-tight text-slate-100">
            Trace<span className="text-emerald-400">2</span>Evals
          </h1>
          <p className="hidden text-xs text-slate-400 sm:block">
            your production failures are your best test cases
          </p>
        </div>

        <div className="flex items-center gap-2">
          <StatBadge label="runs" value={stats.data?.runs_total ?? '—'} />
          <StatBadge
            label="unlabeled"
            value={stats.data?.runs_unlabeled ?? '—'}
            tone={stats.data?.runs_unlabeled ? 'amber' : 'emerald'}
          />
          {stats.data?.median_seconds_per_label != null && (
            <StatBadge
              label="median"
              value={`${stats.data.median_seconds_per_label}s`}
              tone={stats.data.meets_speed_target ? 'emerald' : 'amber'}
              title={`Target: under ${stats.data.target_median_seconds}s per label`}
            />
          )}
          <span
            title="Local-first: no telemetry, no outbound requests, no LLM calls"
            className="hidden rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-300 sm:inline"
          >
            offline
          </span>
        </div>
      </header>

      <nav className="flex flex-wrap gap-1 border-b border-white/10 pb-2">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `rounded-lg px-3 py-1.5 text-sm transition-colors ${
                isActive
                  ? 'bg-emerald-500/15 font-medium text-emerald-200'
                  : 'text-slate-300 hover:bg-white/5'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Navigate to="/runs" replace />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/label" element={<LabelerPage />} />
          <Route path="/label/:runId" element={<LabelerPage />} />
          <Route path="/cases" element={<CasesPage />} />
          <Route path="/export" element={<ExportPage />} />
          <Route path="*" element={<Navigate to="/runs" replace />} />
        </Routes>
      </main>

      <footer className="border-t border-white/10 pt-3 text-xs text-slate-500">
        Trace2Evals · local-first, zero telemetry, no LLM calls ·{' '}
        <a href="/api/docs" className="text-slate-400 underline decoration-dotted">
          API docs
        </a>
      </footer>
    </div>
  )
}
