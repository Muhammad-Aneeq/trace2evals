import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api'
import {
  Card,
  ConfidencePill,
  EmptyState,
  MetricTile,
  StatBadge,
  TraceTimeline,
  VerdictBar,
} from '../components/aurora'
import { useHotkeys } from '../hooks/useHotkeys'
import { useSessionStats } from '../hooks/useSessionStats'
import { FAILURE_TAGS, type FailureTag, type RunDetail, type Verdict } from '../types'

/**
 * The labeler (spec 03 F3): TraceTimeline in the centre, VerdictBar at the bottom, keyboard legend
 * visible, auto-advance to the next unlabeled run on commit.
 *
 * The flow is deliberately: keystroke -> optimistic advance -> next run already in hand. The label
 * response carries `next_run_id`, so advancing costs no extra round trip and the UI never stalls
 * between runs. That is what makes a sub-10-second median achievable at all.
 */
export function LabelerPage() {
  const { runId } = useParams<{ runId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [verdict, setVerdict] = useState<Verdict | null>(null)
  const [tags, setTags] = useState<string[]>([])
  const [note, setNote] = useState('')
  const [cursor, setCursor] = useState(-1)
  const [expandedSteps, setExpandedSteps] = useState<number[]>([])
  const [showHelp, setShowHelp] = useState(false)
  const [lastLabeled, setLastLabeled] = useState<string | null>(null)
  const noteRef = useRef<HTMLInputElement | null>(null)

  const { stats: session, startTiming, stopTiming } = useSessionStats()

  // With no run id in the URL, ask the server which run is next in the queue.
  const nextQuery = useQuery({
    queryKey: ['next-unlabeled'],
    queryFn: () => api.nextUnlabeled(),
    enabled: !runId,
  })

  const runQuery = useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.getRun(runId as string),
    enabled: Boolean(runId),
  })

  const run: RunDetail | null | undefined = runId ? runQuery.data : nextQuery.data
  const serverStats = useQuery({ queryKey: ['stats'], queryFn: api.getStats })

  // Reset the form and restart the clock whenever a different run comes into view.
  useEffect(() => {
    if (!run) return
    setVerdict(run.verdict)
    setTags(run.tags)
    setNote(run.note)
    setCursor(-1)
    setExpandedSteps([])
    startTiming()
  }, [run?.run_id, startTiming])

  const advance = useCallback(
    (nextRunId: string | null) => {
      if (nextRunId) {
        navigate(`/label/${encodeURIComponent(nextRunId)}`, { replace: true })
      } else {
        // Queue drained: drop back to the id-less route so the empty state shows.
        navigate('/label', { replace: true })
        void queryClient.invalidateQueries({ queryKey: ['next-unlabeled'] })
      }
    },
    [navigate, queryClient],
  )

  const labelMutation = useMutation({
    mutationFn: async () => {
      if (!run || !verdict) throw new Error('nothing to commit')
      const seconds = stopTiming()
      return api.labelRun(run.run_id, { verdict, tags, note, seconds_spent: seconds })
    },
    onSuccess: (response) => {
      setLastLabeled(response.run_id)
      void queryClient.invalidateQueries({ queryKey: ['runs'] })
      void queryClient.invalidateQueries({ queryKey: ['stats'] })
      advance(response.next_run_id)
    },
  })

  const undoMutation = useMutation({
    mutationFn: async (target: string) => api.clearLabel(target),
    onSuccess: (_data, target) => {
      setLastLabeled(null)
      void queryClient.invalidateQueries({ queryKey: ['runs'] })
      void queryClient.invalidateQueries({ queryKey: ['stats'] })
      navigate(`/label/${encodeURIComponent(target)}`, { replace: true })
    },
  })

  const toggleExpand = useCallback((index: number) => {
    setExpandedSteps((previous) =>
      previous.includes(index) ? previous.filter((item) => item !== index) : [...previous, index],
    )
  }, [])

  const toggleTag = useCallback((tag: FailureTag) => {
    setTags((previous) =>
      previous.includes(tag) ? previous.filter((item) => item !== tag) : [...previous, tag],
    )
  }, [])

  const skip = useCallback(async () => {
    if (!run) return
    const next = await api.nextUnlabeled(run.run_id)
    advance(next ? next.run_id : null)
  }, [run, advance])

  const commit = useCallback(() => {
    if (!verdict || labelMutation.isPending) return
    if (tags.includes('other') && !note.trim()) {
      noteRef.current?.focus()
      return
    }
    labelMutation.mutate()
  }, [verdict, tags, note, labelMutation])

  const stepCount = run?.steps.length ?? 0

  useHotkeys(
    {
      r: () => setVerdict('right'),
      w: () => setVerdict('wrong'),
      p: () => setVerdict('partial'),
      '1': () => toggleTag(FAILURE_TAGS[0]),
      '2': () => toggleTag(FAILURE_TAGS[1]),
      '3': () => toggleTag(FAILURE_TAGS[2]),
      '4': () => toggleTag(FAILURE_TAGS[3]),
      '5': () => toggleTag(FAILURE_TAGS[4]),
      '6': () => toggleTag(FAILURE_TAGS[5]),
      '7': () => toggleTag(FAILURE_TAGS[6]),
      j: () => setCursor((c) => Math.min(c + 1, stepCount - 1)),
      k: () => setCursor((c) => Math.max(c - 1, 0)),
      arrowdown: () => setCursor((c) => Math.min(c + 1, stepCount - 1)),
      arrowup: () => setCursor((c) => Math.max(c - 1, 0)),
      x: () => {
        // Expand whichever step the cursor is on; default to the first if it has not moved yet.
        const target = cursor >= 0 ? cursor : 0
        if (stepCount > 0) {
          setCursor(target)
          toggleExpand(target)
        }
      },
      enter: () => commit(),
      s: () => void skip(),
      n: () => noteRef.current?.focus(),
      u: () => {
        if (lastLabeled) undoMutation.mutate(lastLabeled)
      },
      '?': () => setShowHelp((value) => !value),
      escape: () => {
        setShowHelp(false)
        ;(document.activeElement as HTMLElement | null)?.blur()
      },
    },
    Boolean(run),
  )

  if (runQuery.isLoading || nextQuery.isLoading) {
    return <p className="py-16 text-center text-sm text-slate-500">Loading run…</p>
  }

  if (!run) {
    const total = serverStats.data?.runs_total ?? 0
    return (
      <Card>
        <EmptyState
          title={total === 0 ? 'No runs imported yet' : 'Everything is labeled'}
          icon={total === 0 ? '[ ]' : '✓'}
          action={
            <Link
              to={total === 0 ? '/import' : '/runs'}
              className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 text-sm text-emerald-200"
            >
              {total === 0 ? 'Import traces' : 'Review the run list'}
            </Link>
          }
        >
          {total === 0 ? (
            <>
              Import an OpenTelemetry JSON or LangSmith JSONL export to start labeling. From the CLI:{' '}
              <code className="font-mono text-slate-300">t2e import fixtures/otel/</code>
            </>
          ) : (
            <>
              All {total} run{total === 1 ? '' : 's'} carry a verdict. Build eval cases from them on the
              Cases screen, then export a version.
            </>
          )}
        </EmptyState>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Session stats: speed is the product claim, so it is on screen while you work. */}
      <div className="grid gap-3 sm:grid-cols-4">
        <MetricTile label="Labeled this session" value={session.count} />
        <MetricTile
          label="Median / label"
          value={session.medianSeconds === null ? '—' : `${session.medianSeconds}s`}
          hint={`target < ${10}s`}
          tone={session.meetsTarget === null ? 'default' : session.meetsTarget ? 'emerald' : 'amber'}
        />
        <MetricTile
          label="Last label"
          value={session.lastSeconds === null ? '—' : `${session.lastSeconds}s`}
        />
        <MetricTile
          label="Remaining"
          value={serverStats.data?.runs_unlabeled ?? '—'}
          hint={`of ${serverStats.data?.runs_total ?? 0} runs`}
        />
      </div>

      <Card
        padded={false}
        title={
          <span className="flex items-center gap-2">
            <span className="font-mono text-xs text-slate-400">{run.run_id.slice(0, 16)}</span>
            <ConfidencePill verdict={run.verdict} />
          </span>
        }
        subtitle={run.started ? new Date(run.started).toLocaleString() : 'no timestamp'}
        actions={
          <>
            <StatBadge label="source" value={run.source} />
            <StatBadge label="steps" value={run.steps.length} />
            <StatBadge
              label="took"
              value={run.duration === null ? '—' : `${(run.duration / 1000).toFixed(1)}s`}
            />
            <StatBadge
              label="outcome"
              value={run.outcome.status}
              tone={run.outcome.status === 'error' ? 'rose' : 'emerald'}
            />
          </>
        }
      >
        <div className="space-y-4 px-5 py-4">
          <div>
            <div className="mb-1 text-[0.7rem] uppercase tracking-wider text-slate-500">Input</div>
            <p className="whitespace-pre-wrap rounded-lg bg-navy-950/60 p-3 text-sm leading-relaxed text-slate-200">
              {run.input || '(no input recorded)'}
            </p>
          </div>

          <div>
            <div className="mb-1 text-[0.7rem] uppercase tracking-wider text-slate-500">
              Final output
            </div>
            <p className="whitespace-pre-wrap rounded-lg bg-navy-950/60 p-3 text-sm leading-relaxed text-slate-200">
              {run.outcome.output || '(no output recorded)'}
            </p>
            {run.outcome.error && (
              <p className="mt-2 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
                {run.outcome.error}
              </p>
            )}
          </div>

          <div>
            <div className="mb-1 text-[0.7rem] uppercase tracking-wider text-slate-500">
              Timeline · {run.steps.length} step{run.steps.length === 1 ? '' : 's'}
            </div>
            <TraceTimeline
              steps={run.steps}
              cursor={cursor}
              onCursorChange={setCursor}
              expanded={expandedSteps}
              onToggleExpand={toggleExpand}
            />
          </div>
        </div>
      </Card>

      <div className="sticky bottom-4">
        <VerdictBar
          verdict={verdict}
          tags={tags}
          note={note}
          onVerdict={setVerdict}
          onToggleTag={toggleTag}
          onNote={setNote}
          onCommit={commit}
          onSkip={() => void skip()}
          busy={labelMutation.isPending}
          existing={Boolean(run.verdict)}
          noteRef={noteRef}
        />
      </div>

      {labelMutation.isError && (
        <p role="alert" className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
          Could not save the label: {(labelMutation.error as Error).message}
        </p>
      )}

      {showHelp && (
        <Card title="Keyboard reference">
          <dl className="grid gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
            {[
              ['R / W / P', 'verdict: right, wrong, partial'],
              ['1 – 7', 'toggle a failure tag'],
              ['J / K or ↓ / ↑', 'move the step cursor'],
              ['X or click', 'expand a step payload'],
              ['N', 'focus the note field'],
              ['Enter', 'commit and advance to the next unlabeled run'],
              ['S', 'skip without labeling'],
              ['U', 'undo the label you just committed'],
              ['Esc', 'leave the note field / close this panel'],
              ['?', 'toggle this panel'],
            ].map(([keys, meaning]) => (
              <div key={keys} className="flex items-baseline justify-between gap-4 border-b border-white/5 py-1">
                <dt className="font-mono text-xs text-emerald-300">{keys}</dt>
                <dd className="text-right text-slate-300">{meaning}</dd>
              </div>
            ))}
          </dl>
        </Card>
      )}
    </div>
  )
}
