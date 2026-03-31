import { useEffect, useState } from 'react'
import { BarChart2, Zap, DollarSign, Hash } from 'lucide-react'
import toast from 'react-hot-toast'

import { fetchUsageStats, type UsageStats } from '../api/usage'
import { Card, CardContent, CardHeader } from '../components/ui/Card'

function fmt(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k'
  return String(n)
}

function fmtCost(usd: number | null): string {
  if (usd === null) return '—'
  if (usd === 0) return '$0.00'
  if (usd < 0.0001) return '<$0.0001'
  return '$' + usd.toFixed(4)
}

function shortModel(model: string): string {
  // Zkrátí dlouhé názvy modelů jako "meta-llama/Llama-3.3-70B-Instruct-Turbo"
  const parts = model.split('/')
  return parts[parts.length - 1]
}

export function UsagePage() {
  const [stats, setStats] = useState<UsageStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchUsageStats()
      .then(setStats)
      .catch(() => toast.error('Nepodařilo se načíst statistiky'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8">
        <p className="text-sm text-[var(--text-muted)]">Načítám...</p>
      </div>
    )
  }

  if (!stats) return null

  const totalTokens = stats.total_input_tokens + stats.total_output_tokens

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-[var(--text)]">Spotřeba</h1>
      </div>

      {/* Přehledové karty */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard icon={<Hash size={15} />} label="Volání" value={String(stats.total_calls)} />
        <StatCard icon={<Zap size={15} />} label="Tokeny celkem" value={fmt(totalTokens)} />
        <StatCard icon={<Zap size={15} />} label="Vstup" value={fmt(stats.total_input_tokens)} />
        <StatCard icon={<DollarSign size={15} />} label="Náklady" value={fmtCost(stats.total_cost_usd)} />
      </div>

      {/* Per model */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--text)]">
            <BarChart2 size={16} className="text-[var(--accent)]" />
            Podle modelu
          </div>
        </CardHeader>
        <CardContent>
          {stats.by_model.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)]">Žádná data</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-[var(--text-muted)] border-b border-[var(--border)]">
                    <th className="pb-2 pr-4 font-medium">Model</th>
                    <th className="pb-2 pr-4 font-medium">Operace</th>
                    <th className="pb-2 pr-4 font-medium text-right">Volání</th>
                    <th className="pb-2 pr-4 font-medium text-right">Vstup</th>
                    <th className="pb-2 pr-4 font-medium text-right">Výstup</th>
                    <th className="pb-2 font-medium text-right">Cena</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.by_model.map((row, i) => (
                    <tr
                      key={i}
                      className="border-b border-[var(--border)] last:border-0 text-[var(--text)]"
                    >
                      <td className="py-2 pr-4">
                        <div className="font-mono text-xs leading-tight">{shortModel(row.model)}</div>
                        <div className="text-xs text-[var(--text-muted)]">{row.provider}</div>
                      </td>
                      <td className="py-2 pr-4 text-xs text-[var(--text-muted)]">{row.operation}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{row.calls}</td>
                      <td className="py-2 pr-4 text-right tabular-nums text-xs">{fmt(row.input_tokens)}</td>
                      <td className="py-2 pr-4 text-right tabular-nums text-xs">{fmt(row.output_tokens)}</td>
                      <td className="py-2 text-right tabular-nums font-mono text-xs">{fmtCost(row.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Per den */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--text)]">
            <BarChart2 size={16} className="text-[var(--accent)]" />
            Posledních 30 dní
          </div>
        </CardHeader>
        <CardContent>
          {stats.by_day.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)]">Žádná data</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-[var(--text-muted)] border-b border-[var(--border)]">
                    <th className="pb-2 pr-4 font-medium">Den</th>
                    <th className="pb-2 pr-4 font-medium text-right">Volání</th>
                    <th className="pb-2 pr-4 font-medium text-right">Vstup</th>
                    <th className="pb-2 pr-4 font-medium text-right">Výstup</th>
                    <th className="pb-2 font-medium text-right">Cena</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.by_day.map((row, i) => (
                    <tr
                      key={i}
                      className="border-b border-[var(--border)] last:border-0 text-[var(--text)]"
                    >
                      <td className="py-2 pr-4 font-mono text-xs">{row.day}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{row.calls}</td>
                      <td className="py-2 pr-4 text-right tabular-nums text-xs">{fmt(row.input_tokens)}</td>
                      <td className="py-2 pr-4 text-right tabular-nums text-xs">{fmt(row.output_tokens)}</td>
                      <td className="py-2 text-right tabular-nums font-mono text-xs">{fmtCost(row.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helper komponenta
// ---------------------------------------------------------------------------

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string
}) {
  return (
    <div className="flex flex-col gap-1 px-4 py-3 rounded-lg bg-[var(--surface-2)] border border-[var(--border)]">
      <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
        <span className="text-[var(--accent)]">{icon}</span>
        {label}
      </div>
      <div className="text-lg font-semibold tabular-nums text-[var(--text)]">{value}</div>
    </div>
  )
}
