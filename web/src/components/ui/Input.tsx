import React from 'react'

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  hint?: string
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, className = '', ...props }, ref) => {
    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wide">
            {label}
          </label>
        )}
        <input
          ref={ref}
          className={[
            'w-full rounded-lg bg-[var(--surface-2)] border px-3 py-2 text-sm text-[var(--text)]',
            'placeholder:text-[var(--text-muted)]',
            'outline-none transition-colors',
            error
              ? 'border-[var(--danger)] focus:border-[var(--danger)]'
              : 'border-[var(--border)] focus:border-[var(--accent)]',
            className,
          ].join(' ')}
          {...props}
        />
        {hint && !error && <p className="text-xs text-[var(--text-muted)]">{hint}</p>}
        {error && <p className="text-xs text-[var(--danger)]">{error}</p>}
      </div>
    )
  }
)

Input.displayName = 'Input'
