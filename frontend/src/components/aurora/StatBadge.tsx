import type { ReactNode } from 'react'

interface StatBadgeProps {
  label: ReactNode
  value: ReactNode
  tone?: 'default' | 'accent' | 'amber' | 'rose'
  title?: string
}

const tones = {
  default: 'border-white/10 bg-white/5 text-slate-300',
  accent: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300',
  amber: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  rose: 'border-rose-500/40 bg-rose-500/10 text-rose-300',
} as const

/** A compact label/value pill for headers and toolbars. */
export function StatBadge({ label, value, tone = 'default', title }: StatBadgeProps) {
  return (
    <span
      title={title}
      className={`inline-flex items-baseline gap-1.5 rounded-full border px-2.5 py-1 text-xs ${tones[tone]}`}
    >
      <span className="opacity-70">{label}</span>
      <span className="font-semibold tabular-nums">{value}</span>
    </span>
  )
}
