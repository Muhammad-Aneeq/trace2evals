import type { Ref } from 'react'

import { FAILURE_TAGS, TAG_LABELS, type FailureTag, type Verdict } from '../../types'
import { verdictClasses } from './tokens'

interface VerdictBarProps {
  verdict: Verdict | null
  tags: string[]
  note: string
  onVerdict: (verdict: Verdict) => void
  onToggleTag: (tag: FailureTag) => void
  onNote: (note: string) => void
  onCommit: () => void
  onSkip: () => void
  busy?: boolean
  /** Shown when the run already has a label, so re-labeling is obviously a replacement. */
  existing?: boolean
  /** Lets the parent's N hotkey focus the note field. */
  noteRef?: Ref<HTMLInputElement>
}

const VERDICT_KEYS: { verdict: Verdict; key: string; label: string }[] = [
  { verdict: 'right', key: 'R', label: 'Right' },
  { verdict: 'wrong', key: 'W', label: 'Wrong' },
  { verdict: 'partial', key: 'P', label: 'Partial' },
]

/**
 * The verdict bar (spec 03 F3): R/W/P plus the closed failure taxonomy on digits 1-7, with the
 * keyboard legend always visible. Built for this repo rather than imported from aurora-ui, per the
 * build adaptation note in PLAN.md (D-002).
 *
 * Every control is a real button as well as a hotkey: the keyboard is the fast path, not the only
 * path, and mouse users must not be locked out.
 */
export function VerdictBar({
  verdict,
  tags,
  note,
  onVerdict,
  onToggleTag,
  onNote,
  onCommit,
  onSkip,
  busy = false,
  existing = false,
  noteRef,
}: VerdictBarProps) {
  const needsTag = verdict === 'wrong' || verdict === 'partial'
  const noteRequired = tags.includes('other')

  return (
    <div className="glass rounded-2xl">
      <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-4 py-3">
        {VERDICT_KEYS.map(({ verdict: value, key, label }) => (
          <button
            key={value}
            type="button"
            onClick={() => onVerdict(value)}
            aria-pressed={verdict === value}
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
              verdict === value
                ? verdictClasses[value]
                : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
            }`}
          >
            <span className="kbd">{key}</span>
            {label}
          </button>
        ))}

        <div className="ml-auto flex items-center gap-2">
          {existing && (
            <span className="text-xs text-slate-400">replacing an existing label</span>
          )}
          <button
            type="button"
            onClick={onSkip}
            className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-slate-300 hover:bg-white/10"
          >
            <span className="kbd">S</span>
            Skip
          </button>
          <button
            type="button"
            onClick={onCommit}
            disabled={!verdict || busy || (noteRequired && !note.trim())}
            className="inline-flex items-center gap-2 rounded-lg border border-cyan-500/50 bg-cyan-500/20 px-3 py-1.5 text-sm font-semibold text-cyan-200 transition-colors hover:bg-cyan-500/30 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span className="kbd">↵</span>
            {busy ? 'Saving…' : 'Commit & next'}
          </button>
        </div>
      </div>

      <div className="px-4 py-3">
        <div className="mb-2 flex items-baseline gap-2">
          <span className="text-[0.7rem] uppercase tracking-wider text-slate-400">Failure tags</span>
          {needsTag && tags.length === 0 && (
            <span className="text-[0.7rem] text-amber-300">
              optional, but a tag is what makes the distribution useful
            </span>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5">
          {FAILURE_TAGS.map((tag, index) => {
            const active = tags.includes(tag)
            return (
              <button
                key={tag}
                type="button"
                onClick={() => onToggleTag(tag)}
                aria-pressed={active}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs transition-colors ${
                  active
                    ? 'border-amber-500/50 bg-amber-500/20 text-amber-200'
                    : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
                }`}
              >
                <span className="kbd">{index + 1}</span>
                {TAG_LABELS[tag]}
              </button>
            )
          })}
        </div>

        <div className="mt-3">
          <label htmlFor="label-note" className="sr-only">
            Note
          </label>
          <input
            id="label-note"
            ref={noteRef}
            type="text"
            value={note}
            onChange={(event) => onNote(event.target.value)}
            placeholder={
              noteRequired
                ? 'Required for the "other" tag: what went wrong?'
                : 'Optional note (press N to focus)'
            }
            className={`w-full rounded-lg border bg-ink-950/60 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500 ${
              noteRequired && !note.trim() ? 'border-amber-500/50' : 'border-white/10'
            }`}
          />
        </div>

        <p className="mt-2.5 text-[0.7rem] text-slate-500">
          <span className="kbd">R</span> <span className="kbd">W</span> <span className="kbd">P</span>{' '}
          verdict · <span className="kbd">1</span>–<span className="kbd">7</span> tags ·{' '}
          <span className="kbd">J</span>/<span className="kbd">K</span> step ·{' '}
          <span className="kbd">X</span> expand · <span className="kbd">N</span> note ·{' '}
          <span className="kbd">↵</span> commit · <span className="kbd">S</span> skip ·{' '}
          <span className="kbd">U</span> undo · <span className="kbd">?</span> help
        </p>
      </div>
    </div>
  )
}
