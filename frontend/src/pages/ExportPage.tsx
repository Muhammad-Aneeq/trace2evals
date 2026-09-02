import { Card, EmptyState } from '../components/aurora'

/**
 * Export screen (spec 03 sec 9 screen 5). Exporters land in Phase 3; the CLI equivalent will be
 * `t2e export --version v1 --format jsonl,pytest`.
 */
export function ExportPage() {
  return (
    <Card title="Export">
      <EmptyState title="Exporters arrive in Phase 3" icon="->">
        This screen will write a versioned cases.jsonl, a generated pytest stub, and an optional
        Promptfoo file - all of which you keep, in formats no platform owns.
      </EmptyState>
    </Card>
  )
}
