import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api'
import { Card, EmptyState, RiskTag, StatBadge } from '../components/aurora'
import {
  ASSERTION_HINTS,
  ASSERTION_KINDS,
  ASSERTION_LABELS,
  type AssertionKind,
  type EvalCase,
  type Expectation,
} from '../types'

/**
 * Cases screen (spec 03 sec 9 screen 4): cases grouped by version, with an expectation editor whose
 * pickers are limited to the five v1 assertion kinds.
 *
 * Building a case from a labeled run pre-fills its expectations from the failure tags (spec 03 F4), so
 * the common path is "review and confirm" rather than "author from scratch".
 */
export function CasesPage() {
  const queryClient = useQueryClient()
  const [version, setVersion] = useState('v1')
  const [editing, setEditing] = useState<number | null>(null)

  const casesQuery = useQuery({ queryKey: ['cases'], queryFn: () => api.listCases() })
  const stats = useQuery({ queryKey: ['stats'], queryFn: api.getStats })
  const labeledRuns = useQuery({
    queryKey: ['runs', { labeled: true }],
    queryFn: () => api.listRuns({ labeled: true, unlabeled_first: false, limit: 500 }),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['cases'] })
    void queryClient.invalidateQueries({ queryKey: ['stats'] })
  }

  const createFromRun = useMutation({
    mutationFn: (runId: string) => api.createCase({ version, run_id: runId }),
    onSuccess: invalidate,
  })

  const createManual = useMutation({
    mutationFn: () =>
      api.createCase({ version, input: 'Describe the input the agent should handle.', expectations: [] }),
    onSuccess: (created) => {
      invalidate()
      setEditing(created.id)
    },
  })

  const removeCase = useMutation({
    mutationFn: (caseId: number) => api.deleteCase(caseId),
    onSuccess: invalidate,
  })

  const cases = casesQuery.data ?? []
  const byVersion = cases.reduce<Record<string, EvalCase[]>>((acc, item) => {
    ;(acc[item.version] ??= []).push(item)
    return acc
  }, {})

  const casedRunIds = new Set(cases.map((item) => item.run_id).filter(Boolean))
  const candidates = (labeledRuns.data ?? []).filter((run) => !casedRunIds.has(run.run_id))

  return (
    <div className="space-y-4">
      <Card
        title="Eval cases"
        subtitle="Labeled runs become versioned cases. Assertions are pre-filled from the failure tags."
        actions={
          <>
            <StatBadge label="cases" value={stats.data?.cases_total ?? '—'} />
            <label className="inline-flex items-center gap-1.5 text-xs text-slate-300">
              version
              <input
                value={version}
                onChange={(event) => setVersion(event.target.value)}
                className="w-16 rounded-md border border-white/10 bg-navy-900/80 px-2 py-1 font-mono text-xs"
                aria-label="Case version"
              />
            </label>
            <button
              type="button"
              onClick={() => createManual.mutate()}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-slate-200 hover:bg-white/10"
            >
              New manual case
            </button>
          </>
        }
      >
        {candidates.length === 0 ? (
          <p className="text-sm text-slate-400">
            {labeledRuns.data?.length
              ? 'Every labeled run already has a case.'
              : 'No labeled runs yet — label some on the Labeler screen first.'}{' '}
            <Link to="/label" className="text-emerald-300 underline decoration-dotted">
              Go to the labeler
            </Link>
          </p>
        ) : (
          <>
            <p className="mb-2 text-sm text-slate-400">
              {candidates.length} labeled run{candidates.length === 1 ? '' : 's'} without a case:
            </p>
            <ul className="space-y-1.5">
              {candidates.slice(0, 12).map((run) => (
                <li
                  key={run.run_id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-slate-200">
                      {run.input_preview}
                    </span>
                    <span className="mt-0.5 flex flex-wrap gap-1">
                      <span className="font-mono text-[0.7rem] text-slate-500">{run.verdict}</span>
                      {run.tags.map((tag) => (
                        <RiskTag key={tag} tag={tag} />
                      ))}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => createFromRun.mutate(run.run_id)}
                    disabled={createFromRun.isPending}
                    className="shrink-0 rounded-lg border border-emerald-500/50 bg-emerald-500/20 px-3 py-1.5 text-xs font-semibold text-emerald-200 disabled:opacity-50"
                  >
                    Build case
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>

      {cases.length === 0 ? (
        <Card>
          <EmptyState title="No cases yet" icon="{ }">
            Build a case from a labeled run above. Its assertions arrive pre-filled from the failure
            tags you picked, so most cases are a review rather than an authoring job.
          </EmptyState>
        </Card>
      ) : (
        Object.entries(byVersion)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([groupVersion, groupCases]) => (
            <Card
              key={groupVersion}
              padded={false}
              title={`Version ${groupVersion}`}
              subtitle={`${groupCases.length} case(s)`}
              actions={
                <Link
                  to="/export"
                  className="rounded-lg border border-emerald-500/50 bg-emerald-500/20 px-3 py-1.5 text-sm font-semibold text-emerald-200"
                >
                  Export {groupVersion}
                </Link>
              }
            >
              <ul className="divide-y divide-white/5">
                {groupCases.map((item) => (
                  <CaseRow
                    key={item.id}
                    item={item}
                    editing={editing === item.id}
                    onEdit={() => setEditing(editing === item.id ? null : item.id)}
                    onDelete={() => removeCase.mutate(item.id)}
                    onSaved={invalidate}
                  />
                ))}
              </ul>
            </Card>
          ))
      )}
    </div>
  )
}

interface CaseRowProps {
  item: EvalCase
  editing: boolean
  onEdit: () => void
  onDelete: () => void
  onSaved: () => void
}

function CaseRow({ item, editing, onEdit, onDelete, onSaved }: CaseRowProps) {
  const [input, setInput] = useState(item.input)
  const [expectations, setExpectations] = useState<Expectation[]>(item.expectations)

  const save = useMutation({
    mutationFn: () =>
      api.updateCase(item.id, { version: item.version, input, expectations, tags: item.tags }),
    onSuccess: onSaved,
  })

  const addExpectation = (kind: AssertionKind) => {
    const blank: Record<AssertionKind, Expectation> = {
      must_call_tool: { kind, tool: '' },
      must_escalate: { kind },
      must_cite: { kind, min_count: 1 },
      output_matches_regex: { kind, pattern: '' },
      output_matches_schema: { kind, schema: { type: 'object' } },
    }
    setExpectations((previous) => [...previous, blank[kind]])
  }

  const update = (index: number, patch: Partial<Expectation>) => {
    setExpectations((previous) =>
      previous.map((expectation, i) => (i === index ? { ...expectation, ...patch } : expectation)),
    )
  }

  return (
    <li className="px-5 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="font-mono text-xs text-slate-500">
              {item.version}-{String(item.id).padStart(4, '0')}
            </span>
            {item.run_id ? (
              <Link
                to={`/label/${encodeURIComponent(item.run_id)}`}
                className="font-mono text-[0.7rem] text-emerald-300/80 underline decoration-dotted"
              >
                from {item.run_id.slice(0, 12)}
              </Link>
            ) : (
              <span className="font-mono text-[0.7rem] text-slate-500">manual</span>
            )}
            {item.tags.map((tag) => (
              <span
                key={tag}
                className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[0.65rem] text-slate-400"
              >
                {tag}
              </span>
            ))}
          </div>
          <p className="mt-1 truncate text-sm text-slate-200">{item.input}</p>
          {!editing && (
            <ul className="mt-1.5 space-y-0.5">
              {item.expectations.length === 0 ? (
                <li className="text-xs text-amber-300">
                  no expectations — this case would assert nothing
                </li>
              ) : (
                item.expectations.map((expectation, index) => (
                  <li key={index} className="text-xs text-slate-400">
                    <span className="font-mono text-emerald-300/90">{expectation.kind}</span>
                    {expectation.tool ? ` · ${expectation.tool}` : ''}
                    {expectation.pattern ? ` · /${expectation.pattern}/` : ''}
                    {expectation.sources ? ` · ${expectation.sources.join(', ')}` : ''}
                    {expectation.min_count !== undefined ? ` · min ${expectation.min_count}` : ''}
                    {expectation.note ? (
                      <span className="text-slate-600"> — {expectation.note}</span>
                    ) : null}
                  </li>
                ))
              )}
            </ul>
          )}
        </div>

        <div className="flex shrink-0 gap-1.5">
          <button
            type="button"
            onClick={onEdit}
            className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-slate-200 hover:bg-white/10"
          >
            {editing ? 'Close' : 'Edit'}
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs text-rose-200 hover:bg-rose-500/20"
          >
            Delete
          </button>
        </div>
      </div>

      {editing && (
        <div className="mt-3 animate-fade-in space-y-3 rounded-xl border border-white/10 bg-navy-950/50 p-3">
          <div>
            <label
              htmlFor={`case-input-${item.id}`}
              className="mb-1 block text-[0.7rem] uppercase tracking-wider text-slate-500"
            >
              Input
            </label>
            <textarea
              id={`case-input-${item.id}`}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              rows={3}
              className="w-full rounded-lg border border-white/10 bg-navy-950/70 px-3 py-2 text-sm text-slate-200"
            />
          </div>

          <div>
            <div className="mb-1.5 flex flex-wrap items-center gap-2">
              <span className="text-[0.7rem] uppercase tracking-wider text-slate-500">
                Expected behaviour
              </span>
              <span className="text-[0.7rem] text-slate-600">
                v1 supports exactly five assertion kinds
              </span>
            </div>

            <div className="mb-2 flex flex-wrap gap-1.5">
              {ASSERTION_KINDS.map((kind) => (
                <button
                  key={kind}
                  type="button"
                  onClick={() => addExpectation(kind)}
                  title={ASSERTION_HINTS[kind]}
                  className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs text-slate-300 hover:bg-white/10"
                >
                  + {ASSERTION_LABELS[kind]}
                </button>
              ))}
            </div>

            <ul className="space-y-2">
              {expectations.map((expectation, index) => (
                <li
                  key={index}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-2"
                >
                  <span className="font-mono text-xs text-emerald-300">{expectation.kind}</span>

                  {expectation.kind === 'must_call_tool' && (
                    <input
                      value={expectation.tool ?? ''}
                      onChange={(event) => update(index, { tool: event.target.value })}
                      placeholder="get_invoice"
                      aria-label="Tool name"
                      className="flex-1 rounded border border-white/10 bg-navy-950/70 px-2 py-1 font-mono text-xs"
                    />
                  )}

                  {expectation.kind === 'output_matches_regex' && (
                    <input
                      value={expectation.pattern ?? ''}
                      onChange={(event) => update(index, { pattern: event.target.value })}
                      placeholder="\\bINV-\\d+\\b"
                      aria-label="Regular expression"
                      className="flex-1 rounded border border-white/10 bg-navy-950/70 px-2 py-1 font-mono text-xs"
                    />
                  )}

                  {expectation.kind === 'must_cite' && (
                    <>
                      <input
                        type="number"
                        min={1}
                        value={expectation.min_count ?? 1}
                        onChange={(event) =>
                          update(index, { min_count: Number(event.target.value) })
                        }
                        aria-label="Minimum citations"
                        className="w-16 rounded border border-white/10 bg-navy-950/70 px-2 py-1 text-xs"
                      />
                      <input
                        value={(expectation.sources ?? []).join(', ')}
                        onChange={(event) =>
                          update(index, {
                            sources: event.target.value
                              .split(',')
                              .map((value) => value.trim())
                              .filter(Boolean),
                          })
                        }
                        placeholder="required ids, e.g. INV-2026-0881"
                        aria-label="Required sources"
                        className="flex-1 rounded border border-white/10 bg-navy-950/70 px-2 py-1 font-mono text-xs"
                      />
                    </>
                  )}

                  {expectation.kind === 'output_matches_schema' && (
                    <textarea
                      value={JSON.stringify(expectation.schema ?? {}, null, 0)}
                      onChange={(event) => {
                        try {
                          update(index, { schema: JSON.parse(event.target.value) })
                        } catch {
                          // Keep the keystroke; an invalid intermediate state is normal while typing.
                          update(index, { schema: event.target.value })
                        }
                      }}
                      rows={2}
                      aria-label="JSON Schema"
                      className="flex-1 rounded border border-white/10 bg-navy-950/70 px-2 py-1 font-mono text-xs"
                    />
                  )}

                  {expectation.kind === 'must_escalate' && (
                    <span className="flex-1 text-xs text-slate-500">no parameters</span>
                  )}

                  <button
                    type="button"
                    onClick={() => setExpectations((p) => p.filter((_, i) => i !== index))}
                    aria-label={`Remove ${expectation.kind}`}
                    className="rounded border border-white/10 px-1.5 py-0.5 text-xs text-slate-400 hover:text-rose-300"
                  >
                    remove
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => save.mutate()}
              disabled={save.isPending}
              className="rounded-lg border border-emerald-500/50 bg-emerald-500/20 px-3 py-1.5 text-sm font-semibold text-emerald-200 disabled:opacity-50"
            >
              {save.isPending ? 'Saving…' : 'Save case'}
            </button>
            {save.isError && (
              <span className="text-xs text-rose-300">{(save.error as Error).message}</span>
            )}
          </div>
        </div>
      )}
    </li>
  )
}
