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

/** The v1 assertion language is capped at five kinds (spec 03 sec 14). */
export const ASSERTION_KINDS = [
  'must_call_tool',
  'must_escalate',
  'must_cite',
  'output_matches_regex',
  'output_matches_schema',
] as const

export type AssertionKind = (typeof ASSERTION_KINDS)[number]

export const ASSERTION_LABELS: Record<AssertionKind, string> = {
  must_call_tool: 'Must call tool',
  must_escalate: 'Must escalate',
  must_cite: 'Must cite',
  output_matches_regex: 'Output matches regex',
  output_matches_schema: 'Output matches schema',
}

/** What each kind needs from the author, so the editor can render the right field. */
export const ASSERTION_HINTS: Record<AssertionKind, string> = {
  must_call_tool: 'Tool name the agent must call, e.g. get_invoice',
  must_escalate: 'No parameters: the agent must hand off rather than guess',
  must_cite: 'Minimum citation count, or specific evidence ids',
  output_matches_regex: 'Regular expression the output must match',
  output_matches_schema: 'JSON Schema the output must satisfy',
}

export interface Expectation {
  kind: AssertionKind
  note?: string
  // must_call_tool
  tool?: string
  allow_any?: boolean
  // must_cite
  sources?: string[]
  min_count?: number
  // output_matches_regex
  pattern?: string
  flags?: string
  // output_matches_schema
  schema?: unknown
  [key: string]: unknown
}

export interface EvalCase {
  id: number
  version: string
  run_id: string | null
  input: string
  expectations: Expectation[]
  tags: string[]
  created_at: string | null
}

export interface CaseSuggestion {
  version: string
  run_id: string
  input: string
  expectations: Expectation[]
  tags: string[]
}

export interface ExportedFile {
  file: string
  bytes: number
  content?: string
}

export interface ExportResult {
  version: string
  case_count: number
  formats: string[]
  out_dir?: string
  files: ExportedFile[]
}

export interface RunFilters {
  source?: Source | ''
  has_error?: boolean | null
  min_duration_ms?: number | null
  max_duration_ms?: number | null
  labeled?: boolean | null
  unlabeled_first?: boolean
}
