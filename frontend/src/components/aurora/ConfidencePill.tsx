import type { Verdict } from '../../types'
import { verdictClasses } from './tokens'

const labels: Record<Verdict, string> = {
  right: 'Right',
  wrong: 'Wrong',
  partial: 'Partial',
}

/**
 * Verdict pill. Named ConfidencePill in spec 00 A2, where it maps 0-1 to colour+label; this tool
 * has no confidence scores (no LLM in the MVP), so it carries the discrete verdict instead.
 */
export function ConfidencePill({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) {
    return (
      <span className="inline-flex items-center rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-xs text-slate-400">
        Unlabeled
      </span>
    )
  }
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${verdictClasses[verdict]}`}
    >
      {labels[verdict]}
    </span>
  )
}
