import type { ReactNode } from 'react'

interface MetricTileProps {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: 'default' | 'accent' | 'amber' | 'rose'
}

const valueTones = {
  default: 'text-slate-100',
  accent: 'text-cyan-300',
  amber: 'text-amber-300',
  rose: 'text-rose-300',
} as const

/** A single number worth looking at. Used for the live session stats (spec 03 sec 9). */
export function MetricTile({ label, value, hint, tone = 'default' }: MetricTileProps) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3">
      <div className="text-[0.7rem] uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`mt-1 font-display text-2xl font-semibold tabular-nums ${valueTones[tone]}`}>
        {value}
      </div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  )
}
