interface BadgeProps {
  children: React.ReactNode
  variant?: 'default' | 'success' | 'warning' | 'danger'
}

const variants = {
  default: 'bg-[var(--surface-2)] text-[var(--text-muted)]',
  success: 'bg-[var(--success)]/10 text-[var(--success)]',
  warning: 'bg-yellow-500/10 text-yellow-400',
  danger: 'bg-[var(--danger)]/10 text-[var(--danger)]',
}

export function Badge({ children, variant = 'default' }: BadgeProps) {
  return (
    <span className={['inline-flex items-center px-2 py-0.5 rounded text-xs font-medium', variants[variant]].join(' ')}>
      {children}
    </span>
  )
}
