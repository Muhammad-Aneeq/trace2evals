import { useEffect, useRef } from 'react'

export type HotkeyHandler = (event: KeyboardEvent) => void

/**
 * Global key bindings for the labeler.
 *
 * Two rules that matter for a keyboard-first tool:
 *  - keystrokes are ignored while the user is typing in a field, otherwise the note box would fire
 *    verdicts on every letter
 *  - modifier combinations are ignored, so browser shortcuts (Ctrl+R, Cmd+K) keep working
 *
 * Handlers are kept in a ref so the listener is attached once and never re-bound mid-session,
 * which would drop a keystroke.
 */
export function useHotkeys(bindings: Record<string, HotkeyHandler>, enabled = true) {
  const bindingsRef = useRef(bindings)
  bindingsRef.current = bindings

  useEffect(() => {
    if (!enabled) return

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return

      const target = event.target as HTMLElement | null
      const typing =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        target?.isContentEditable === true

      // Escape always gets through: it is how you leave the note field.
      if (typing && event.key !== 'Escape') return

      const handler = bindingsRef.current[event.key.toLowerCase()] ?? bindingsRef.current[event.key]
      if (handler) {
        event.preventDefault()
        handler(event)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [enabled])
}
