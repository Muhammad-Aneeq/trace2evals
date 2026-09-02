import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'

import { api } from '../api'
import { Card, EmptyState, StatBadge } from '../components/aurora'
import type { ExportResult } from '../types'

const FORMATS = [
  {
    id: 'jsonl',
    label: 'cases.jsonl',
    blurb: 'The versioned suite you keep. Schema documented in docs/cases_schema.md.',
  },
  {
    id: 'pytest',
    label: 'test_cases.py',
    blurb: 'Generated pytest stub with assertion helpers. Needs your agent adapter to run.',
  },
  {
    id: 'promptfoo',
    label: 'promptfooconfig.yaml',
    blurb: 'Optional. Weaker for tool/escalation assertions — Promptfoo cannot see the tool trace.',
  },
] as const

/**
 * Export screen (spec 03 sec 9 screen 5): version notes, format checkboxes, download.
 *
 * Files are rendered in the browser and downloaded via a blob, so nothing is uploaded and no server
 * write is needed to get your suite out. `write_to_disk` is the CLI's job.
 */
export function ExportPage() {
  const [version, setVersion] = useState('v1')
  const [notes, setNotes] = useState('')
  const [selected, setSelected] = useState<string[]>(['jsonl', 'pytest'])
  const [result, setResult] = useState<ExportResult | null>(null)

  const stats = useQuery({ queryKey: ['stats'], queryFn: api.getStats })
  const versions = Object.keys(stats.data?.cases_by_version ?? {})

  const runExport = useMutation({
    mutationFn: () =>
      api.exportCases({ version, format: selected.join(','), notes, write_to_disk: false }),
    onSuccess: setResult,
  })

  const toggle = (id: string) => {
    setSelected((previous) =>
      previous.includes(id) ? previous.filter((item) => item !== id) : [...previous, id],
    )
  }

  const download = (filename: string, content: string) => {
    // A blob download keeps everything local: no upload, no server round trip for the file.
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const caseCount = stats.data?.cases_by_version?.[version] ?? 0

  return (
    <div className="space-y-4">
      <Card
        title="Export"
        subtitle="Framework-neutral output you own. Nothing here is locked to this tool."
        actions={<StatBadge label="cases" value={stats.data?.cases_total ?? '—'} />}
      >
        {versions.length === 0 ? (
          <EmptyState title="No cases to export yet" icon="->">
            Build cases from your labeled runs first.{' '}
            <Link to="/cases" className="text-emerald-300 underline decoration-dotted">
              Go to Cases
            </Link>
          </EmptyState>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-end gap-4">
              <label className="text-sm text-slate-300">
                <span className="mb-1 block text-[0.7rem] uppercase tracking-wider text-slate-500">
                  Version
                </span>
                <select
                  value={version}
                  onChange={(event) => setVersion(event.target.value)}
                  className="rounded-lg border border-white/10 bg-navy-900/80 px-2.5 py-1.5 font-mono text-sm"
                >
                  {versions.map((item) => (
                    <option key={item} value={item}>
                      {item} ({stats.data?.cases_by_version?.[item] ?? 0} cases)
                    </option>
                  ))}
                </select>
              </label>

              <label className="min-w-[16rem] flex-1 text-sm text-slate-300">
                <span className="mb-1 block text-[0.7rem] uppercase tracking-wider text-slate-500">
                  Version notes
                </span>
                <input
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  placeholder="e.g. first pass over week 33 failures"
                  className="w-full rounded-lg border border-white/10 bg-navy-950/60 px-3 py-1.5 text-sm"
                />
              </label>
            </div>

            <fieldset>
              <legend className="mb-1.5 text-[0.7rem] uppercase tracking-wider text-slate-500">
                Formats
              </legend>
              <div className="space-y-1.5">
                {FORMATS.map((format) => (
                  <label
                    key={format.id}
                    className="flex items-start gap-2.5 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2"
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(format.id)}
                      onChange={() => toggle(format.id)}
                      className="mt-0.5 accent-emerald-500"
                    />
                    <span>
                      <span className="block font-mono text-sm text-slate-200">{format.label}</span>
                      <span className="block text-xs text-slate-500">{format.blurb}</span>
                    </span>
                  </label>
                ))}
              </div>
              {selected.includes('pytest') && !selected.includes('jsonl') && (
                <p className="mt-1.5 text-xs text-amber-300">
                  cases.jsonl will be included anyway: the pytest stub reads its cases from it.
                </p>
              )}
            </fieldset>

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => runExport.mutate()}
                disabled={selected.length === 0 || caseCount === 0 || runExport.isPending}
                className="rounded-lg border border-emerald-500/50 bg-emerald-500/20 px-4 py-2 text-sm font-semibold text-emerald-200 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {runExport.isPending ? 'Generating…' : `Generate ${version}`}
              </button>
              <span className="text-xs text-slate-500">
                {caseCount} case{caseCount === 1 ? '' : 's'} at {version} · or run{' '}
                <code className="font-mono text-slate-400">
                  t2e export --version {version} --format {selected.join(',') || 'jsonl'}
                </code>
              </span>
            </div>

            {runExport.isError && (
              <p
                role="alert"
                className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200"
              >
                Export failed: {(runExport.error as Error).message}
              </p>
            )}
          </div>
        )}
      </Card>

      {result && (
        <Card
          padded={false}
          title={`Exported ${result.version}`}
          subtitle={`${result.case_count} case(s) · ${result.formats.join(', ')}`}
        >
          <ul className="divide-y divide-white/5">
            {result.files.map((file) => (
              <li key={file.file} className="px-5 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono text-sm text-slate-200">{file.file}</span>
                  <span className="flex items-center gap-2">
                    <span className="text-xs text-slate-500">{file.bytes} bytes</span>
                    {file.content !== undefined && (
                      <button
                        type="button"
                        onClick={() => download(file.file, file.content as string)}
                        className="rounded-md border border-emerald-500/40 bg-emerald-500/15 px-2 py-1 text-xs text-emerald-200"
                      >
                        Download
                      </button>
                    )}
                  </span>
                </div>
                {file.content !== undefined && (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-slate-400">Preview</summary>
                    <pre className="payload mt-1.5">{file.content.slice(0, 4000)}</pre>
                  </details>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="What you get">
        <ul className="space-y-1.5 text-sm text-slate-300">
          <li>
            <code className="font-mono text-emerald-300">cases.jsonl</code> — one JSON object per
            case, with a pinned <code className="font-mono">schema_version</code> so a reader can
            refuse a shape it does not understand.
          </li>
          <li>
            <code className="font-mono text-emerald-300">test_cases.py</code> — a real pytest file. It
            imports assertion helpers from <code className="font-mono">t2e.assertions</code> and calls
            a <code className="font-mono">run_agent</code> fixture that you write; until you do, it
            tells you so rather than passing vacuously.
          </li>
          <li>
            <code className="font-mono text-emerald-300">promptfooconfig.yaml</code> — convenient for
            prompt iteration. Two of the five assertion kinds are weaker there, and the generated file
            says so at the top.
          </li>
        </ul>
      </Card>
    </div>
  )
}
