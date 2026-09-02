import { TAG_LABELS, type FailureTag } from '../../types'

interface RiskTagProps {
  tag: string
  onRemove?: () => void
}

/** A failure-taxonomy chip. */
export function RiskTag({ tag, onRemove }: RiskTagProps) {
  const label = TAG_LABELS[tag as FailureTag] ?? tag
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[0.7rem] font-medium text-amber-200">
      {label}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${label}`}
          className="text-amber-300/70 hover:text-amber-100"
        >
          x
        </button>
      )}
    </span>
  )
}
