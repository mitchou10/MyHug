import { ChevronLeft, ChevronRight, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { formatCount } from '../../format'
import type { Dataset } from '../../mockData'
import { hue } from './seed'

const SHORT = ['label', 'source', 'lang', 'juridiction']
const PAGE = 5

function LabelBadge({ value }: { value: string | number }) {
  const h = hue(String(value))
  return (
    <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium" style={{ background: `hsl(${h} 70% 90%)`, color: `hsl(${h} 60% 25%)` }}>
      {value}
    </span>
  )
}

/** Text: like the Hugging Face viewer, with splits, search, pagination, labels, and a click to read a whole row. */
export function TextViewer({ dataset: d }: { dataset: Dataset }) {
  const { t } = useTranslation()
  const cut = Math.ceil(d.sample.length * 0.75)
  const splits = [
    { name: 'train', rows: d.sample.slice(0, cut), total: Math.round(d.rows * 0.8) },
    { name: 'test', rows: d.sample.slice(cut), total: Math.round(d.rows * 0.2) },
  ]
  const [split, setSplit] = useState('train')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const [open, setOpen] = useState<number | null>(null)

  const current = splits.find((s) => s.name === split)!
  const rows = useMemo(() => current.rows.map((r, i) => ({ r, i })).filter(({ r }) => !query.trim() || r.join(' ').toLowerCase().includes(query.trim().toLowerCase())), [current, query])
  const pages = Math.max(1, Math.ceil(rows.length / PAGE))
  const visible = rows.slice(page * PAGE, page * PAGE + PAGE)

  const labelCol = d.columns.findIndex((c) => SHORT.includes(c))
  const counts = new Map<string, number>()
  if (labelCol >= 0) current.rows.forEach((r) => counts.set(String(r[labelCol]), (counts.get(String(r[labelCol])) ?? 0) + 1))

  const reset = (fn: () => void) => { fn(); setPage(0); setOpen(null) }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {splits.map((s) => (
          <Button key={s.name} size="sm" variant={split === s.name ? 'default' : 'outline'} onClick={() => reset(() => setSplit(s.name))}>
            {s.name} <span className="opacity-70">{formatCount(s.total)}</span>
          </Button>
        ))}
        <div className="relative ml-auto min-w-48 flex-1 sm:max-w-xs">
          <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
          <Input className="pl-8" placeholder={t('datasets.viewer.search')} value={query} onChange={(e) => reset(() => setQuery(e.target.value))} />
        </div>
      </div>

      {labelCol >= 0 && (
        <div className="space-y-1.5">
          <div className="flex h-2 overflow-hidden rounded-full bg-muted">
            {[...counts].map(([k, v]) => <span key={k} title={`${k}: ${v}`} style={{ width: `${(v / current.rows.length) * 100}%`, background: `hsl(${hue(k)} 65% 55%)` }} />)}
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            {d.columns[labelCol]}: {[...counts].map(([k, v]) => <span key={k} className="flex items-center gap-1"><LabelBadge value={k} />{Math.round((v / current.rows.length) * 100)}%</span>)}
          </div>
        </div>
      )}

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-12">#</TableHead>
              {d.columns.map((c, j) => <TableHead key={c}>{c} <span className="text-xs font-normal text-muted-foreground">{typeof d.sample[0][j] === 'number' ? 'int' : SHORT.includes(c) ? 'class' : 'string'}</span></TableHead>)}
            </TableRow>
          </TableHeader>
          <TableBody>
            {visible.map(({ r, i }) => (
              <TableRow key={i} className="cursor-pointer" onClick={() => setOpen(open === i ? null : i)}>
                <TableCell className="text-muted-foreground">{i}</TableCell>
                {r.map((cell, j) => (
                  <TableCell key={j} className={cn('whitespace-normal', !SHORT.includes(d.columns[j]) && 'max-w-md', open !== i && !SHORT.includes(d.columns[j]) && 'line-clamp-2')}>
                    {SHORT.includes(d.columns[j]) ? <LabelBadge value={cell} /> : cell}
                  </TableCell>
                ))}
              </TableRow>
            ))}
            {!visible.length && <TableRow><TableCell colSpan={d.columns.length + 1} className="py-8 text-center text-muted-foreground">{t('datasets.none')}</TableCell></TableRow>}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>{t('datasets.viewer.rowsShown', { from: rows.length ? page * PAGE + 1 : 0, to: Math.min(rows.length, page * PAGE + PAGE), total: rows.length })}</span>
        <div className="flex items-center gap-1">
          <Button size="icon" variant="outline" disabled={page === 0} onClick={() => { setPage(page - 1); setOpen(null) }} aria-label="Previous"><ChevronLeft /></Button>
          <span className="px-2">{page + 1} / {pages}</span>
          <Button size="icon" variant="outline" disabled={page >= pages - 1} onClick={() => { setPage(page + 1); setOpen(null) }} aria-label="Next"><ChevronRight /></Button>
        </div>
      </div>
    </div>
  )
}
