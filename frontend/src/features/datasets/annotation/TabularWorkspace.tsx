import { ArrowLeft, ChevronDown, ChevronUp } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Container } from '@/components/Container'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { Dataset } from '../mockData'
import { matchesFormat, VALUE_TYPES, type ValueType } from './format'
import { ScaleInput } from './ScaleInput'
import { StringListInput } from './StringListInput'
import { labelsOf, useAnnotations, withLabel, type Answer, type CellNote, type ColumnNote, type LabelDef, type AnnotationProject, commitAnswer, rejectProposal, type Proposal } from './store'
import { ProposalBanner } from './ProposalBanner'
import { color } from './ui'

const shown = (v: string | number | undefined) => (v === '' || v === undefined ? '∅' : String(v))

/** The grid: every row visible, a side panel to annotate what is selected. Everything is saved as you go. */
export function TabularWorkspace({ dataset: d, project }: { dataset: Dataset; project: AnnotationProject }) {
  const { t } = useTranslation()
  const all = useAnnotations()
  const store = all.answers[project.id] ?? {}
  const proposed = all.proposals[project.id] ?? {}
  const task = project.task
  /** Labelling a row and giving it a number work the same way: one row selected at a time. */
  const rowMode = task === 'row_label' || task === 'regression'
  const rows = d.sample
  const [sel, setSel] = useState({ r: task === 'column_schema' ? -1 : 0, c: rowMode ? -1 : 0 })

  /** A row shows its proposal until a human has answered it: the first change turns the proposal into their answer. */
  const ans = (r: number): Answer => store[r] ?? proposed[r]?.answer ?? {}
  const pending = (r: number): Proposal | null => (store[r] ? null : (proposed[r] ?? null))
  const setRow = (r: number, patch: Partial<Answer>) => commitAnswer(project.id, r, { ...ans(r), ...patch }, pending(r))
  const labelName = (id?: string) => project.labels.find((l) => l.id === id)?.name ?? t('datasets.annotation.deletedLabel')
  const cols = ans(0).columns ?? {}

  const setNote = (r: number, c: number, note: CellNote | null) => {
    const cells = { ...ans(r).cells }
    if (note) cells[c] = note
    else delete cells[c]
    setRow(r, { cells })
  }
  const setColumn = (c: number, patch: Partial<ColumnNote>) => setRow(0, { columns: { ...ans(0).columns, [c]: { ...ans(0).columns?.[c], ...patch } } })

  const move = (dr: number, dc: number) => setSel((s) => ({ r: task === 'column_schema' ? -1 : Math.min(rows.length - 1, Math.max(0, s.r + dr)), c: rowMode ? -1 : Math.min(d.columns.length - 1, Math.max(0, s.c + dc)) }))
  const pick = (l: LabelDef) => {
    if (task === 'row_label') { const n = withLabel(ans(sel.r), l.id, project.multiLabel); setRow(sel.r, { label: n.label, labels: n.labels }) }
    else if (task === 'cell_review') { const n = ans(sel.r).cells?.[sel.c]; setNote(sel.r, sel.c, n?.issue === l.id ? null : { ...n, issue: l.id }) }
    else setColumn(sel.c, { role: cols[sel.c]?.role === l.id ? undefined : l.id })
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('textarea,input,select')) return
      const n = Number(e.key)
      if (n >= 1 && n <= project.labels.length) return pick(project.labels[n - 1])
      const m: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1], Enter: [1, 0] }
      if (m[e.key]) { e.preventDefault(); move(...m[e.key]) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const progress =
    task === 'regression' ? t('datasets.annotation.tab.progressRows', { done: rows.filter((_, r) => store[r]?.value !== undefined).length, total: rows.length })
    : task === 'row_label' ? t('datasets.annotation.tab.progressRows', { done: rows.filter((_, r) => labelsOf(store[r] ?? {}).length).length, total: rows.length })
    : task === 'cell_review' ? t('datasets.annotation.tab.progressCells', { done: rows.reduce((n, _, r) => n + Object.keys(store[r]?.cells ?? {}).length, 0), rows: rows.filter((_, r) => Object.keys(store[r]?.cells ?? {}).length).length })
    : t('datasets.annotation.tab.progressColumns', { done: d.columns.filter((_, c) => store[0]?.columns?.[c]?.role).length, total: d.columns.length })

  const labelButtons = (selected: string[]) => (
    <div className="grid gap-1.5">
      {project.labels.map((l, i) => (
        <Button key={l.id} variant="outline" title={l.description} onClick={() => pick(l)}
          className={cn('h-auto justify-start gap-2 py-1.5 text-left whitespace-normal', selected.includes(l.id) && 'ring-2 ring-primary')} style={selected.includes(l.id) ? color(l.id) : undefined}>
          <kbd className="rounded bg-background/70 px-1.5 text-xs">{i + 1}</kbd>
          <span className="flex flex-col"><span>{l.name}</span>{l.description && <span className="text-xs font-normal opacity-80">{l.description}</span>}</span>
        </Button>
      ))}
    </div>
  )

  const row = rows[sel.r]
  /** The row whose proposal is on screen: the selected one, or row 0 for the columns (a schema is one answer). */
  const proposalRow = task === 'column_schema' ? 0 : sel.r
  const schema = d.schema?.[sel.c]
  const note = ans(sel.r).cells?.[sel.c]
  const colNote = cols[sel.c]
  const expected = schema?.formats?.length ? ({ id: '', name: '', description: '', formats: schema.formats, valueType: schema.valueType } satisfies LabelDef) : null
  const section = (title: string, body: ReactNode) => <div className="space-y-1.5"><h3 className="text-sm font-medium">{title}</h3>{body}</div>

  return (
    <Container className="max-w-7xl py-6">
      <Link to={`/datasets/${d.owner}/${d.name}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />{d.owner}/{d.name}</Link>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">{project.name}</h1>
        <Badge variant="secondary">{t(`datasets.annotation.tasks.${task}.title`)}</Badge>
        <span className="ml-auto text-sm text-muted-foreground">{progress}</span>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{t(task === 'regression' ? 'datasets.annotation.tab.hintValue' : task === 'row_label' ? 'datasets.annotation.tab.hintRow' : task === 'cell_review' ? 'datasets.annotation.tab.hintCell' : 'datasets.annotation.tab.hintColumn')}</p>

      <div className="mt-4 grid items-start gap-4 lg:grid-cols-[1fr_20rem]">
        <div className="max-h-[75vh] overflow-auto rounded-lg border">
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-background">
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                {rowMode && <TableHead>{t('datasets.annotation.tab.annotation')}</TableHead>}
                {d.columns.map((c, j) => (
                  <TableHead key={c} onClick={() => task === 'column_schema' && setSel({ r: -1, c: j })} className={cn(task === 'column_schema' && 'cursor-pointer hover:bg-muted/50', task === 'column_schema' && sel.c === j && 'bg-primary/10')}>
                    <div>{c}</div>
                    {task === 'column_schema' && cols[j]?.role && <span className="rounded-full border px-1.5 text-[10px] font-medium" style={color(cols[j].role!)}>{labelName(cols[j].role)}</span>}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r, i) => (
                <TableRow key={i} onClick={() => rowMode && setSel({ r: i, c: -1 })} className={cn(rowMode && 'cursor-pointer', rowMode && sel.r === i && 'bg-primary/10')}>
                  <TableCell className="text-muted-foreground">{i + 1}</TableCell>
                  {rowMode && <TableCell className={cn(pending(i) && 'italic opacity-60')}>{task === 'regression' ? (ans(i).value !== undefined ? <span className="font-mono font-medium">{ans(i).value}{project.scale?.unit && ` ${project.scale.unit}`}</span> : <span className="text-muted-foreground">—</span>) : labelsOf(ans(i)).length ? <span className="flex flex-wrap gap-1">{labelsOf(ans(i)).map((id) => <span key={id} className="rounded-full border px-2 py-0.5 text-xs font-medium" style={color(id)}>{labelName(id)}</span>)}</span> : <span className="text-muted-foreground">—</span>}</TableCell>}
                  {r.map((cell, j) => {
                    const n = ans(i).cells?.[j]
                    return (
                      <TableCell key={j} onClick={() => task === 'cell_review' && setSel({ r: i, c: j })}
                        className={cn(task === 'cell_review' && 'cursor-pointer', task === 'cell_review' && sel.r === i && sel.c === j && 'bg-primary/10 outline-2 -outline-offset-2 outline-primary', task === 'column_schema' && sel.c === j && 'bg-primary/5', cell === '' && 'text-muted-foreground', n && pending(i) && 'opacity-70 outline-1 -outline-offset-1 outline-dashed outline-current')}
                        style={n ? color(n.issue) : undefined}>
                        {shown(cell)}
                        {n && <span className="ml-1 text-[10px] font-semibold">{labelName(n.issue)}{n.corrected ? ` → ${n.corrected}` : ''}</span>}
                      </TableCell>
                    )
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <aside className="space-y-4 rounded-lg border p-4 lg:sticky lg:top-4">
          {proposalRow >= 0 && pending(proposalRow) && (
            <ProposalBanner proposal={pending(proposalRow)!} edited={false} onAccept={() => commitAnswer(project.id, proposalRow, pending(proposalRow)!.answer, pending(proposalRow))} onReject={() => rejectProposal(project.id, proposalRow, pending(proposalRow)!)} />
          )}
          {rowMode && (sel.r < 0 ? <p className="text-sm text-muted-foreground">{t('datasets.annotation.tab.pickRow')}</p> : (
            <>
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">{t('datasets.annotation.tab.row', { n: sel.r + 1 })}</h2>
                <div className="flex gap-1">
                  <Button size="icon" variant="outline" aria-label={t('datasets.annotation.tab.prev')} onClick={() => move(-1, 0)}><ChevronUp /></Button>
                  <Button size="icon" variant="outline" aria-label={t('datasets.annotation.tab.next')} onClick={() => move(1, 0)}><ChevronDown /></Button>
                </div>
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-sm">
                {d.columns.map((c, j) => <div key={c} className="contents"><dt className="text-muted-foreground">{c}</dt><dd className="font-medium">{shown(row[j])}</dd></div>)}
              </dl>
              {task === 'regression' && project.scale ? <ScaleInput scale={project.scale} value={ans(sel.r).value} onChange={(value) => setRow(sel.r, { value })} /> : labelButtons(labelsOf(ans(sel.r)))}
              {section(`${t('datasets.annotation.reason')} (${t('datasets.annotation.optional')})`,
                <Textarea rows={2} placeholder={t('datasets.annotation.reasonPlaceholder')} value={ans(sel.r).reason ?? ''} onChange={(e) => setRow(sel.r, { reason: e.target.value })} />)}
            </>
          ))}

          {task === 'cell_review' && (
            <>
              <div>
                <h2 className="font-semibold">{d.columns[sel.c]} <span className="font-normal text-muted-foreground">· {t('datasets.annotation.tab.row', { n: sel.r + 1 })}</span></h2>
                <p className="mt-1 text-sm">{t('datasets.annotation.tab.value')}: <span className="font-mono font-medium">{shown(row?.[sel.c])}</span></p>
                {schema && <p className="text-xs text-muted-foreground">{t(`datasets.annotation.types.${schema.valueType}`)}{schema.unit ? ` · ${schema.unit}` : ''}{schema.formats?.length ? ` · ${t('datasets.annotation.tab.expectedFormat')}: ${schema.formats.join(' | ')}` : ''}</p>}
              </div>
              {labelButtons(note?.issue ? [note.issue] : [])}
              {note && (
                <>
                  {section(t('datasets.annotation.tab.corrected'), (
                    <>
                      <Input className={cn('font-mono', note.corrected && expected && !matchesFormat(note.corrected, expected) && 'border-destructive')} value={note.corrected ?? ''} placeholder={schema?.formats?.[0]} onChange={(e) => setNote(sel.r, sel.c, { ...note, corrected: e.target.value })} />
                      {note.corrected && expected && !matchesFormat(note.corrected, expected) && <p className="text-xs text-destructive">{t('datasets.annotation.tab.mismatch', { format: schema!.formats!.join(' | ') })}</p>}
                    </>
                  ))}
                  {section(`${t('datasets.annotation.reason')} (${t('datasets.annotation.optional')})`, <Textarea rows={2} placeholder={t('datasets.annotation.reasonPlaceholder')} value={note.reason ?? ''} onChange={(e) => setNote(sel.r, sel.c, { ...note, reason: e.target.value })} />)}
                  <Button variant="ghost" size="sm" onClick={() => setNote(sel.r, sel.c, null)}>{t('datasets.annotation.tab.clear')}</Button>
                </>
              )}
              {!note && <p className="text-sm text-muted-foreground">{t('datasets.annotation.tab.noIssue')}</p>}
            </>
          )}

          {task === 'column_schema' && (sel.c < 0 ? <p className="text-sm text-muted-foreground">{t('datasets.annotation.tab.pickColumn')}</p> : (
            <>
              <div>
                <h2 className="font-semibold">{d.columns[sel.c]}</h2>
                <p className="mt-1 truncate text-xs text-muted-foreground">{rows.slice(0, 4).map((r) => shown(r[sel.c])).join(' · ')}</p>
              </div>
              {section(t('datasets.annotation.tab.role'), labelButtons(colNote?.role ? [colNote.role] : []))}
              {section(t('datasets.annotation.valueType'), (
                <select value={colNote?.valueType ?? ''} onChange={(e) => setColumn(sel.c, { valueType: (e.target.value || undefined) as ValueType | undefined })} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                  <option value="">—</option>
                  {VALUE_TYPES.map((v) => <option key={v} value={v}>{t(`datasets.annotation.types.${v}`)}</option>)}
                </select>
              ))}
              {section(t('datasets.annotation.formats'), <StringListInput mono value={colNote?.formats ?? []} onChange={(formats) => setColumn(sel.c, { formats })} label={t('datasets.annotation.formats')} placeholder={t(colNote?.valueType === 'date' ? 'datasets.annotation.formatDate' : 'datasets.annotation.formatOther')} />)}
              {section(t('datasets.annotation.tab.unit'), <Input value={colNote?.unit ?? ''} placeholder="m², €, kg…" onChange={(e) => setColumn(sel.c, { unit: e.target.value })} />)}
              {section(t('datasets.annotation.tab.description'), <Textarea rows={2} value={colNote?.description ?? ''} onChange={(e) => setColumn(sel.c, { description: e.target.value })} />)}
            </>
          ))}
          <p className="text-xs text-muted-foreground">{t('datasets.annotation.tab.saved')}</p>
        </aside>
      </div>
    </Container>
  )
}
