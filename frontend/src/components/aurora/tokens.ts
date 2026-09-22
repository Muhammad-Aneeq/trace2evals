/** Aurora design tokens (spec 00 A2), exposed for the few places that need raw values. */
export const tokens = {
  ink: '#161A38',
  inkDeep: '#0B0D1F',
  accent: '#22D3EE',
  verdict: {
    right: '#2DD4BF',
    partial: '#FBBF24',
    wrong: '#FB7185',
  },
  glass: 'rgba(255, 255, 255, 0.04)',
} as const

/** Tailwind class fragments per verdict, so colour stays consistent across components. */
export const verdictClasses = {
  right: 'border-teal-500/40 bg-teal-500/15 text-teal-300',
  partial: 'border-amber-500/40 bg-amber-500/15 text-amber-300',
  wrong: 'border-rose-500/40 bg-rose-500/15 text-rose-300',
} as const

/** One hue per step kind, spaced far enough apart to stay separable in a dense timeline. */
export const stepKindClasses = {
  llm: 'border-blue-400/40 bg-blue-400/10 text-blue-300',
  tool: 'border-cyan-400/40 bg-cyan-400/10 text-cyan-300',
  handoff: 'border-violet-400/40 bg-violet-400/10 text-violet-300',
} as const
