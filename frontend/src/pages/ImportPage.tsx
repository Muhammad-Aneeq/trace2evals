import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '../api'
import { Card, StatBadge, SyntheticDataBanner } from '../components/aurora'
import type { ParseReport } from '../types'

/**
 * Import screen (spec 03 sec 9 screen 1): dropzone plus a per-file parse report.
 *
 * The report is the point. A tool that says "imported!" and hides three malformed records produces
 * silently incomplete eval suites, so every file gets its own row with its own error list.
 */
export function ImportPage() {
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [dragging, setDragging] = useState(false)
  const [format, setFormat] = useState('auto')
  const [redact, setRedact] = useState(true)
  const [reports, setReports] = useState<ParseReport[]>([])

  const importMutation = useMutation({
    mutationFn: (files: File[]) => api.importFiles(files, { format, redact }),
    onSuccess: (result) => {
      setReports(result)
      void queryClient.invalidateQueries({ queryKey: ['runs'] })
      void queryClient.invalidateQueries({ queryKey: ['stats'] })
      void queryClient.invalidateQueries({ queryKey: ['next-unlabeled'] })
    },
  })

  const submit = (files: FileList | null) => {
    if (!files || files.length === 0) return
    importMutation.mutate(Array.from(files))
  }

  const totalRuns = reports.reduce((sum, report) => sum + report.runs_imported, 0)
  const totalErrors = reports.reduce((sum, report) => sum + report.errors.length, 0)
  const totalRedactions = reports.reduce((sum, report) => sum + report.redactions, 0)
  const allFlags = [...new Set(reports.flatMap((report) => report.pii_flags))]

  return (
    <div className="space-y-4">
      <SyntheticDataBanner piiFlags={allFlags} redactionDisabled={!redact} />

      <Card title="Import traces" subtitle="OpenTelemetry JSON or LangSmith run-export JSONL">
        <div
          onDragOver={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            submit(event.dataTransfer.files)
          }}
          className={`rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
            dragging ? 'border-cyan-400/70 bg-cyan-500/10' : 'border-white/15 bg-white/[0.02]'
          }`}
        >
          <p className="text-sm text-slate-300">Drop trace files here</p>
          <p className="mt-1 text-xs text-slate-500">
            .json · .jsonl · .ndjson — several files at once is fine
          </p>
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="mt-4 rounded-lg border border-cyan-500/50 bg-cyan-500/20 px-3 py-1.5 text-sm font-semibold text-cyan-200"
          >
            Choose files
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".json,.jsonl,.ndjson,application/json"
            onChange={(event) => submit(event.target.files)}
            className="hidden"
            aria-label="Trace files to import"
          />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-4">
          <label className="inline-flex items-center gap-2 text-sm text-slate-300">
            Format
            <select
              value={format}
              onChange={(event) => setFormat(event.target.value)}
              className="rounded-lg border border-white/10 bg-ink-900/80 px-2.5 py-1.5 text-sm"
            >
              <option value="auto">Auto-detect</option>
              <option value="otel">OpenTelemetry JSON</option>
              <option value="langsmith">LangSmith JSONL</option>
            </select>
          </label>

          <label className="inline-flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={redact}
              onChange={(event) => setRedact(event.target.checked)}
              className="accent-cyan-500"
            />
            Redact PII-lookalike values on import
          </label>

          <p className="text-xs text-slate-500">
            Files are parsed locally. Nothing is uploaded anywhere.
          </p>
        </div>

        <p className="mt-4 text-xs text-slate-500">
          Prefer the CLI?{' '}
          <code className="font-mono text-slate-400">t2e import fixtures/otel/</code> does the same
          thing and prints the same report.
        </p>
      </Card>

      {importMutation.isPending && (
        <p className="text-sm text-slate-400">Parsing…</p>
      )}

      {importMutation.isError && (
        <p role="alert" className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
          Import failed: {(importMutation.error as Error).message}
        </p>
      )}

      {reports.length > 0 && (
        <Card
          padded={false}
          title="Parse report"
          subtitle={`${reports.length} file(s)`}
          actions={
            <>
              <StatBadge label="runs" value={totalRuns} tone={totalRuns ? 'accent' : 'rose'} />
              <StatBadge
                label="record errors"
                value={totalErrors}
                tone={totalErrors ? 'amber' : 'default'}
              />
              <StatBadge label="redacted" value={totalRedactions} />
              {totalRuns > 0 && (
                <Link
                  to="/label"
                  className="rounded-lg border border-cyan-500/50 bg-cyan-500/20 px-3 py-1.5 text-sm font-semibold text-cyan-200"
                >
                  Start labeling
                </Link>
              )}
            </>
          }
        >
          <ul className="divide-y divide-white/5">
            {reports.map((report) => (
              <li key={report.file} className="px-5 py-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-mono text-sm text-slate-200">{report.file}</span>
                  <span className="text-xs text-slate-400">
                    <span className="font-mono">{report.format}</span> · {report.runs_imported} run(s)
                    · {report.steps_imported} step(s) · {report.records_seen} record(s) seen
                  </span>
                </div>

                {report.redactions > 0 && (
                  <p className="mt-1 text-xs text-cyan-300">
                    redacted {report.redactions} value(s): {report.pii_flags.join(', ')}
                  </p>
                )}

                {report.warnings.map((warning) => (
                  <p key={warning} className="mt-1 text-xs text-amber-300">
                    warning: {warning}
                  </p>
                ))}

                {report.errors.length > 0 && (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-amber-300">
                      {report.errors.length} record error(s) — the rest of the file still imported
                    </summary>
                    <ul className="mt-1.5 space-y-1.5">
                      {report.errors.map((error, index) => (
                        <li key={index} className="rounded-lg bg-ink-950/60 px-3 py-2 text-xs">
                          <div className="font-mono text-slate-400">{error.locator}</div>
                          <div className="text-slate-300">{error.reason}</div>
                          {error.excerpt && (
                            <div className="mt-1 truncate font-mono text-[0.7rem] text-slate-500">
                              {error.excerpt}
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
