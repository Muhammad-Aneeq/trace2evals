import type { ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
  /** Optional heading row; omit for a bare surface. */
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  padded?: boolean
}

/** The frosted-glass surface everything else sits on (spec 00 A2). */
export function Card({ children, className = '', title, subtitle, actions, padded = true }: CardProps) {
  return (
    <section className={`glass rounded-2xl ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-white/10 px-5 py-3.5">
          <div className="min-w-0">
            {title && <h2 className="truncate text-sm font-semibold text-slate-100">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={padded ? 'p-5' : ''}>{children}</div>
    </section>
  )
}
