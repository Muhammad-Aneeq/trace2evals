import type { Step } from '../../types'
import { stepKindClasses } from './tokens'

interface TraceTimelineProps {
  steps: Step[]
  /** Index of the step the keyboard cursor is on, so J/K navigation is visible. */
  cursor?: number
  onCursorChange?: (index: number) => void
  /**
   * Expansion is controlled by the parent so a hotkey (X) and a click can drive the same state.
   * Keeping it internal would leave the keyboard unable to open a payload.
   */
  expanded?: number[]
  onToggleExpand?: (index: number) => void
}

function formatLatency(ms: number | null): string {
  if (ms === null) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function renderPayload(value: unknown): string {
  if (value === null || value === undefined) return '(empty)'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/**
 * The labeling centrepiece (spec 00 A2 TraceTimeline, spec 03 F3): one card per step, expandable
 * to the full payload. Previews are what you scan; the expander is what you check when the preview
 * is not enough to decide.
 */
export function TraceTimeline({
  steps,
  cursor = -1,
  onCursorChange,
  expanded = [],
  onToggleExpand,
}: TraceTimelineProps) {
  const openIndices = new Set(expanded)

  if (steps.length === 0) {
    return (
      <p className="px-5 py-8 text-center text-sm text-slate-500">
        This run has no model, tool or handoff steps.
      </p>
    )
  }

  return (
    <ol className="relative space-y-2 py-1">
      {steps.map((step, index) => {
        const isOpen = openIndices.has(index)
        const isCursor = index === cursor
        return (
          <li key={index} className="relative pl-8">
            {/* Timeline rail */}
            <span
              aria-hidden
              className="absolute left-[0.6875rem] top-8 h-[calc(100%-1rem)] w-px bg-white/10 last:hidden"
            />
            <span
              aria-hidden
              className={`absolute left-2 top-3 h-2.5 w-2.5 rounded-full ring-4 ring-navy-950 ${
                step.error ? 'bg-rose-400' : 'bg-emerald-400/70'
              }`}
            />

            <div
              className={`rounded-xl border transition-colors ${
                isCursor
                  ? 'border-emerald-500/50 bg-emerald-500/[0.07] shadow-glow-emerald'
                  : 'border-white/10 bg-white/[0.03]'
              }`}
            >
              <button
                type="button"
                onClick={() => {
                  onCursorChange?.(index)
                  onToggleExpand?.(index)
                }}
                aria-expanded={isOpen}
                aria-label={`Step ${index + 1}: ${step.kind} ${step.name}`}
                className="flex w-full items-start gap-3 px-3.5 py-2.5 text-left"
              >
                <span className="mt-0.5 w-5 shrink-0 font-mono text-[0.7rem] text-slate-500">
                  {index + 1}
                </span>
                <span
                  className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 font-mono text-[0.65rem] uppercase ${
                    stepKindClasses[step.kind]
                  }`}
                >
                  {step.kind}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline justify-between gap-3">
                    <span className="truncate font-medium text-slate-100">{step.name}</span>
                    <span className="shrink-0 font-mono text-[0.7rem] tabular-nums text-slate-500">
                      {formatLatency(step.latency)}
                    </span>
                  </span>
                  {step.args_preview && (
                    <span className="mt-1 block truncate text-xs text-slate-400">
                      <span className="text-slate-500">in </span>
                      {step.args_preview}
                    </span>
                  )}
                  {step.output_preview && (
                    <span className="mt-0.5 block truncate text-xs text-slate-400">
                      <span className="text-slate-500">out </span>
                      {step.output_preview}
                    </span>
                  )}
                  {step.error && (
                    <span className="mt-1 block truncate text-xs font-medium text-rose-300">
                      error: {step.error}
                    </span>
                  )}
                </span>
                <span aria-hidden className="mt-0.5 shrink-0 font-mono text-xs text-slate-500">
                  {isOpen ? '−' : '+'}
                </span>
              </button>

              {isOpen && (
                <div className="animate-fade-in space-y-3 border-t border-white/10 px-3.5 py-3">
                  <div>
                    <div className="mb-1 text-[0.7rem] uppercase tracking-wider text-slate-500">
                      Arguments
                    </div>
                    <pre className="payload">{renderPayload(step.args)}</pre>
                  </div>
                  <div>
                    <div className="mb-1 text-[0.7rem] uppercase tracking-wider text-slate-500">
                      Output
                    </div>
                    <pre className="payload">{renderPayload(step.output)}</pre>
                  </div>
                </div>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
