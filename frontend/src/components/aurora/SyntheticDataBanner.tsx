interface SyntheticDataBannerProps {
  /** Pattern names the importer flagged as PII-lookalike, if any. */
  piiFlags?: string[]
  /** True when the user imported with redaction switched off. */
  redactionDisabled?: boolean
}

/**
 * Two honesty banners in one component (spec 00 A2 + spec 03 sec 11):
 *  - the standing "data is synthetic" notice, because the shipped fixtures are hand-authored
 *  - the PII-lookalike warning, which only appears when the importer actually flagged something
 */
export function SyntheticDataBanner({ piiFlags = [], redactionDisabled = false }: SyntheticDataBannerProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
        <span aria-hidden>⚠️</span>
        <p>
          <strong className="font-semibold">All bundled data is synthetic.</strong> The fixtures in this
          repository are hand-authored to match real trace formats. No real agent run, customer or
          vendor is represented.
        </p>
      </div>

      {piiFlags.length > 0 && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200"
        >
          <span aria-hidden>🔒</span>
          <p>
            <strong className="font-semibold">Payloads looked like PII</strong> ({piiFlags.join(', ')}).{' '}
            {redactionDisabled
              ? 'Redaction was disabled for this import, so the values were stored as-is.'
              : 'Matching values were redacted on import.'}
          </p>
        </div>
      )}
    </div>
  )
}
