import type { Dataset } from '../../mockData'

/** Time series: a line chart of the series, then the first rows. */
export function TimeSeriesViewer({ dataset: d }: { dataset: Dataset }) {
  const s = d.series ?? []
  if (!s.length) return null
  const W = 640, H = 220, P = 28
  const min = Math.min(...s.map((p) => p.value)), max = Math.max(...s.map((p) => p.value))
  const x = (i: number) => P + (i / (s.length - 1)) * (W - 2 * P)
  const y = (v: number) => H - P - ((v - min) / (max - min || 1)) * (H - 2 * P)
  const line = s.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')

  return (
    <div className="space-y-3">
      <div className="rounded-lg border p-3">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Time series">
          {[0, 0.5, 1].map((t) => (
            <g key={t}>
              <line x1={P} x2={W - P} y1={H - P - t * (H - 2 * P)} y2={H - P - t * (H - 2 * P)} className="stroke-border" />
              <text x={P - 4} y={H - P - t * (H - 2 * P) + 4} textAnchor="end" className="fill-muted-foreground text-[10px]">{Math.round(min + t * (max - min))}</text>
            </g>
          ))}
          <path d={`${line} L${x(s.length - 1)},${H - P} L${x(0)},${H - P} Z`} className="fill-primary/10" />
          <path d={line} fill="none" strokeWidth={2} className="stroke-primary" />
          <text x={P} y={H - 8} className="fill-muted-foreground text-[10px]">{s[0].date}</text>
          <text x={W - P} y={H - 8} textAnchor="end" className="fill-muted-foreground text-[10px]">{s[s.length - 1].date}</text>
        </svg>
      </div>
      <div className="overflow-hidden rounded-lg border text-sm">
        <div className="grid grid-cols-4 bg-muted/50 px-3 py-2 font-medium">{d.columns.map((c) => <span key={c}>{c}</span>)}</div>
        {d.sample.map((r, i) => <div key={i} className="grid grid-cols-4 border-t px-3 py-2">{r.map((c, j) => <span key={j}>{c}</span>)}</div>)}
      </div>
    </div>
  )
}
