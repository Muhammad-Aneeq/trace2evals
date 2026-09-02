import { useCallback, useMemo, useRef, useState } from 'react'

/**
 * Client-side timing for the current labeling session (spec 03 sec 9: "measure and show session
 * stats", target <10s median per simple label).
 *
 * The clock starts when a run is shown and stops when its label is committed, so the measured
 * number is what a labeler actually experienced - decision time included. That value is sent with
 * the label and persisted, which is what makes the median in `t2e stats` a measurement rather than
 * an estimate.
 */
export interface SessionStats {
  count: number
  medianSeconds: number | null
  lastSeconds: number | null
  totalSeconds: number
  /** null until at least one label is timed: an unmeasured target is not a met target. */
  meetsTarget: boolean | null
}

export const TARGET_MEDIAN_SECONDS = 10

function median(values: number[]): number | null {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 1) return sorted[middle] as number
  return ((sorted[middle - 1] as number) + (sorted[middle] as number)) / 2
}

export function useSessionStats() {
  const startedAt = useRef<number | null>(null)
  const [durations, setDurations] = useState<number[]>([])

  /** Call when a run becomes visible. */
  const startTiming = useCallback(() => {
    startedAt.current = performance.now()
  }, [])

  /**
   * Call when a label is committed. Returns the elapsed seconds so the caller can send it with the
   * label, or null when the timer never started (e.g. a label edited from the runs table).
   */
  const stopTiming = useCallback((): number | null => {
    if (startedAt.current === null) return null
    const seconds = (performance.now() - startedAt.current) / 1000
    startedAt.current = null
    setDurations((previous) => [...previous, seconds])
    return Math.round(seconds * 100) / 100
  }, [])

  const reset = useCallback(() => {
    startedAt.current = null
    setDurations([])
  }, [])

  const stats = useMemo<SessionStats>(() => {
    const med = median(durations)
    return {
      count: durations.length,
      medianSeconds: med === null ? null : Math.round(med * 10) / 10,
      lastSeconds:
        durations.length > 0
          ? Math.round((durations[durations.length - 1] as number) * 10) / 10
          : null,
      totalSeconds: Math.round(durations.reduce((sum, value) => sum + value, 0)),
      meetsTarget: med === null ? null : med < TARGET_MEDIAN_SECONDS,
    }
  }, [durations])

  return { stats, startTiming, stopTiming, reset }
}
