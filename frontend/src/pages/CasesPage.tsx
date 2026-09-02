import { Card, EmptyState } from '../components/aurora'

/**
 * Cases screen (spec 03 sec 9 screen 4). The case builder and its assertion pickers land in
 * Phase 3; this placeholder is deliberately honest rather than a fake-looking shell.
 */
export function CasesPage() {
  return (
    <Card title="Eval cases">
      <EmptyState title="The case builder arrives in Phase 3" icon="{ }">
        Labeled runs become versioned eval cases here, with assertions pre-filled from their failure
        tags. Until then, label runs on the Labeler screen - that is the input this screen consumes.
      </EmptyState>
    </Card>
  )
}
