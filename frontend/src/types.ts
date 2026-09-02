/** TypeScript mirrors of the backend Pydantic models (backend/src/t2e/api/routes.py). */

export type Verdict = 'right' | 'wrong' | 'partial'
export type Source = 'otel' | 'langsmith'
export type StepKind = 'llm' | 'tool' | 'handoff'

/** The v1 failure taxonomy is closed (spec 03 F3). Order matches the keyboard digits 1-7. */
export const FAILURE_TAGS = [
  'wrong_tool',
  'bad_args',
  'ungrounded',
  'no_escalation',
  'format_break',
  'hallucinated_fact',
  'other',
] as const

export type FailureTag = (typeof FAILURE_TAGS)[number]

/** Human labels for the taxonomy: the stored keys stay machine-friendly. */
export const TAG_LABELS: Record<FailureTag, string> = {
  wrong_tool: 'Wrong tool',
  bad_args: 'Bad args',
  ungrounded: 'Ungrounded',
  no_escalation: 'No escalation',
  format_break: 'Format break',
  hallucinated_fact: 'Hallucinated fact',
  other: 'Other',
}

export interface RunSummary {
  run_id: string
  source: Source
  started: string | null
  duration: number | null
  has_error: boolean
  n_steps: number
  input_preview: string
  verdict: Verdict | null
  tags: string[]
  note: string
}

export interface Step {
  kind: StepKind
  name: string
  args_preview: string
  output_preview: string
  latency: number | null
  error: string | null
  /** Full payloads for the expanders; previews alone are not enough to label against. */
  args: unknown
  output: unknown
}

export interface Outcome {
  status: 'success' | 'error' | 'unknown'
  output: string
  error: string | null
}

export interface RunDetail {
  run_id: string
  source: Source
  started: string | null
  duration: number | null
  input: string
  outcome: Outcome
  meta: Record<string, unknown>
  steps: Step[]
  verdict: Verdict | null
  tags: string[]
  note: string
  seconds_spent: number | null
}

export interface LabelRequest {
  verdict: Verdict
  tags: string[]
  note?: string
  seconds_spent?: number | null
}

export interface LabelResponse {
  run_id: string
  verdict: Verdict
  tags: string[]
  /** Arrives with the label so auto-advance costs no extra round trip. */
  next_run_id: string | null
  runs_unlabeled: number
}

export interface RecordError {
  locator: string
  reason: string
  excerpt: string
}

export interface ParseReport {
  file: string
  format: string
  records_seen: number
  runs_imported: number
  steps_imported: number
  errors: RecordError[]
  warnings: string[]
  redactions: number
  pii_flags: string[]
}

export interface Stats {
  runs_total: number
  runs_by_source: Record<string, number>
  runs_labeled: number
  runs_unlabeled: number
  runs_with_error: number
  labeled_fraction: number
  verdicts: Record<Verdict, number>
  failure_tags: Record<string, number>
  labels_timed: number
  median_seconds_per_label: number | null
  mean_seconds_per_label: number | null
  fastest_seconds: number | null
  slowest_seconds: number | null
  session_labels: number
  session_median_seconds: number | null
  target_median_seconds: number
  /** null when nothing has been timed: an unmeasured claim is not a passing one. */
  meets_speed_target: boolean | null
  cases_total: number
  cases_by_version: Record<string, number>
  export_versions: { version: string; created_at: string | null; case_count: number; notes: string }[]
}

export interface RunFilters {
  source?: Source | ''
  has_error?: boolean | null
  min_duration_ms?: number | null
  max_duration_ms?: number | null
  labeled?: boolean | null
  unlabeled_first?: boolean
}
