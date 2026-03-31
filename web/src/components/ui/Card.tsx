import React from 'react'

interface CardProps {
  children: React.ReactNode
  className?: string
}

export function Card({ children, className = '' }: CardProps) {
  return (
    <div
      className={[
        'bg-[var(--surface)] border border-[var(--border)] rounded-xl',
        className,
      ].join(' ')}
    >
      {children}
    </div>
  )
}

export function CardHeader({ children, className = '' }: CardProps) {
  return (
    <div className={['px-6 py-4 border-b border-[var(--border)]', className].join(' ')}>
      {children}
    </div>
  )
}

export function CardContent({ children, className = '' }: CardProps) {
  return <div className={['px-6 py-4', className].join(' ')}>{children}</div>
}
