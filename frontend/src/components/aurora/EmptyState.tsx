import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  children?: ReactNode
  action?: ReactNode
  icon?: string
}

export function EmptyState({ title, children, action, icon = '[ ]' }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      <div className="font-mono text-2xl text-slate-600">{icon}</div>
      <h3 className="text-base font-semibold text-slate-200">{title}</h3>
      {children && <div className="max-w-md text-sm leading-relaxed text-slate-400">{children}</div>}
      {action}
    </div>
  )
}
