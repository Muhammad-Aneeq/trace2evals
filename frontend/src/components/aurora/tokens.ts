/** Aurora design tokens (spec 00 A2), exposed for the few places that need raw values. */
export const tokens = {
  navy: '#0B1E3B',
  navyDeep: '#050F1E',
  emerald: '#10B981',
  verdict: {
    right: '#10B981',
    partial: '#F59E0B',
    wrong: '#F43F5E',
  },
  glass: 'rgba(255, 255, 255, 0.04)',
} as const

/** Tailwind class fragments per verdict, so colour stays consistent across components. */
export const verdictClasses = {
  right: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300',
  partial: 'border-amber-500/40 bg-amber-500/15 text-amber-300',
  wrong: 'border-rose-500/40 bg-rose-500/15 text-rose-300',
} as const

export const stepKindClasses = {
  llm: 'border-sky-400/40 bg-sky-400/10 text-sky-300',
  tool: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-300',
  handoff: 'border-violet-400/40 bg-violet-400/10 text-violet-300',
} as const
