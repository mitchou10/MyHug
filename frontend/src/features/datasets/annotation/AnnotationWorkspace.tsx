import { ArrowLeft, Check, SkipForward, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import { Container } from '@/components/Container'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { hue } from '../components/viewers/seed'
import { getDataset } from '../mockData'
import { matchesFormat, needsValue } from './format'
import { saveAnswer, useAnnotations, type Answer, type LabelDef, type Span } from './store'

const color = (id: string) => ({ background: `hsl(${hue(id)} 80% 88%)`, borderColor: `hsl(${hue(id)} 60% 55%)`, color: `hsl(${hue(id)} 60% 20%)` })

/** Where one annotates: one row at a time, labels on the keyboard (1, 2, 3…), Enter to submit. */
export function AnnotationWorkspace() {
  const { t } = useTranslation()
  const { owner, name, projectId } = useParams()
  const d = getDataset(owner, name)
  const { projects, answers } = useAnnotations()
  const project = projects.find((p) => p.id === projectId)
  const textCol = d ? Math.max(0, d.columns.findIndex((c) => c === 'text' || c === 'question')) : 0
  const [idx, setIdx] = useState(0)
  const [draft, setDraft] = useState<Answer>({})
  const [sel, setSel] = useState<{ a: number; b: number } | null>(null)
  /** Where the label menu floats, relative to the text card. */
  const [menu, setMenu] = useState<{ left: number; top: number } | null>(null)
  const card = useRef<HTMLDivElement>(null)

  const rows = d?.sample ?? []
  const text = String(rows[idx]?.[textCol] ?? '')
  const tokens = useMemo(() => text.split(/\s+/).filter(Boolean), [text])
  const saved = answers[projectId ?? '']
  const doneCount = Object.keys(saved ?? {}).length

  const labelOf = (id: string) => project?.labels.find((l) => l.id === id)?.name ?? t('datasets.annotation.deletedLabel')
  const labelDef = (id: string) => project?.labels.find((l) => l.id === id)
  const kindOf = (id: string) => project?.labels.find((l) => l.id === id)?.kind ?? 'entity'
  /** Entities first, then semantic ones: the order of the keys 1, 2, 3… */
  const ordered: LabelDef[] = [...(project?.labels ?? [])].sort((a, b) => Number(a.kind === 'semantic') - Number(b.kind === 'semantic'))

  const clearSel = () => { setSel(null); setMenu(null) }
  const go = (i: number) => { setIdx(i); setDraft(saved?.[i] ?? {}); clearSel() }
  const submit = () => {
    if (!project) return
    saveAnswer(project.id, idx, draft)
    go(Math.min(rows.length - 1, idx + 1))
  }
  const assign = (label: string) => {
    if (project?.task === 'classification') setDraft({ ...draft, label })
    else if (project?.task === 'ner' && sel) {
      const s: Span = { start: Math.min(sel.a, sel.b), end: Math.max(sel.a, sel.b), label }
      // Spans may overlap, and a passage may carry several labels. Choosing a label already given to this passage removes it.
      const same = (x: Span) => x.start === s.start && x.end === s.end && x.label === label
      const spans = draft.spans ?? []
      setDraft({ spans: spans.some(same) ? spans.filter((x) => !same(x)) : [...spans, s].sort((x, y) => x.start - y.start || x.end - y.end) })
    }
  }
  const patchSpan = (s: Span, p: Partial<Span>) => setDraft({ spans: draft.spans!.map((x) => (x === s ? { ...x, ...p } : x)) })

  useEffect(() => {
    const away = (e: globalThis.MouseEvent) => { if (!(e.target as HTMLElement).closest('[role=menu],[data-i],button,input,textarea')) clearSel() }
    window.addEventListener('mousedown', away)
    return () => window.removeEventListener('mousedown', away)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!project || (e.target as HTMLElement).closest('textarea,input')) return
      const n = Number(e.key)
      if (n >= 1 && n <= ordered.length) assign(ordered[n - 1].id)
      else if (e.key === 'Enter') submit()
      else if (e.key === 'Escape') clearSel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (!d || !project) return <NotFoundPage />

  const coveringAt = (i: number) => draft.spans?.filter((s) => i >= s.start && i <= s.end) ?? []
  const onSelection = (l: LabelDef) => !!sel && !!draft.spans?.some((x) => x.start === Math.min(sel.a, sel.b) && x.end === Math.max(sel.a, sel.b) && x.label === l.id)
  const inSel = (i: number) => sel && i >= Math.min(sel.a, sel.b) && i <= Math.max(sel.a, sel.b)
  const openMenuAt = (rect: DOMRect) => {
    const c = card.current!.getBoundingClientRect()
    setMenu({ left: rect.left - c.left + rect.width / 2, top: rect.bottom - c.top + 6 })
  }
  /** A click selects a word; shift + click extends the selection up to this word. */
  const clickToken = (i: number, e: MouseEvent<HTMLElement>) => {
    if (!window.getSelection()?.isCollapsed) return
    setSel(e.shiftKey && sel ? { a: sel.a, b: i } : { a: i, b: i })
    openMenuAt(e.currentTarget.getBoundingClientRect())
  }
  /** Dragging with the mouse: the selection snaps to whole words, and the label menu opens under it. */
  const onTextMouseUp = () => {
    const s = window.getSelection()
    if (!s || s.isCollapsed || !s.rangeCount) return
    const r = s.getRangeAt(0)
    const hit = [...(card.current?.querySelectorAll<HTMLElement>('[data-i]') ?? [])].filter((el) => {
      if (!r.intersectsNode(el)) return false
      // A word only touched by the edge of the selection does not count.
      const w = document.createRange(); w.selectNodeContents(el)
      return r.compareBoundaryPoints(Range.START_TO_END, w) > 0 && r.compareBoundaryPoints(Range.END_TO_START, w) < 0
    })
    if (!hit.length) return
    const ids = hit.map((el) => Number(el.dataset.i))
    setSel({ a: Math.min(...ids), b: Math.max(...ids) })
    const last = r.getClientRects(); openMenuAt(last[last.length - 1] ?? r.getBoundingClientRect())
    s.removeAllRanges()
  }

  const labelButton = (l: LabelDef) => (
    <Button key={l.id} variant="outline" disabled={project.task === 'ner' && !sel} onClick={() => assign(l.id)} title={l.description}
      className={cn('h-auto justify-start gap-2 py-2 text-left whitespace-normal', draft.label === l.id && 'ring-2 ring-primary')} style={project.task === 'ner' || draft.label === l.id ? color(l.id) : undefined}>
      <kbd className="rounded bg-background/70 px-1.5 text-xs">{ordered.indexOf(l) + 1}</kbd>
      <span className="flex flex-col gap-0.5">
        <span>{l.name}{project.task === 'ner' && (l.valueType ?? 'text') !== 'text' && <span className="ml-2 text-xs font-normal opacity-70">{t(`datasets.annotation.types.${l.valueType}`)}</span>}</span>
        {l.description && <span className="text-xs font-normal opacity-80">{l.description}</span>}
        {!!l.formats?.length && <span className="font-mono text-xs font-normal opacity-80">{l.formats.join('  |  ')}</span>}
        {!!l.examples?.length && <span className="text-xs font-normal italic opacity-70">{t('datasets.annotation.ex')} {l.examples.join(' · ')}</span>}
      </span>
    </Button>
  )

  return (
    <Container className="max-w-4xl py-6">
      <Link to={`/datasets/${d.owner}/${d.name}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />{d.owner}/{d.name}</Link>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">{project.name}</h1>
        <Badge variant="secondary">{t(`datasets.annotation.tasks.${project.task}.title`)}</Badge>
        <span className="ml-auto text-sm text-muted-foreground">{t('datasets.annotation.progress', { done: doneCount, total: rows.length })}</span>
      </div>
      <div className="mt-2 flex gap-1">
        {rows.map((_, i) => <button key={i} aria-label={`#${i}`} onClick={() => go(i)} className={cn('h-1.5 flex-1 rounded-full', saved?.[i] ? 'bg-primary' : 'bg-muted', i === idx && 'ring-2 ring-ring ring-offset-1')} />)}
      </div>

      <div ref={card} className="relative mt-6 rounded-xl border p-6">
        <div className="mb-3 text-xs text-muted-foreground">{t('datasets.annotation.row', { n: idx })}</div>
        {project.task === 'ner' ? (
          <p className="text-lg leading-[2.75rem]" onMouseDown={clearSel} onMouseUp={onTextMouseUp}>
            {tokens.map((tok, i) => {
              const covering = coveringAt(i)
              // The first entity paints the word; every other span (semantic, or a second label) is a stacked bar below it.
              const ent = covering.find((x) => kindOf(x.label) === 'entity')
              const bars = covering.filter((x) => x !== ent)
              return (
                <span key={i} style={bars.length ? { boxShadow: bars.map((x, n) => `inset 0 -${(n + 1) * 3}px 0 hsl(${hue(x.label)} 60% 50%)`).join(',') } : undefined}>
                  <span data-i={i} onClick={(e) => clickToken(i, e)} style={ent ? color(ent.label) : undefined}
                    className={cn('cursor-text rounded border border-transparent px-1 py-0.5', !ent && 'hover:bg-muted', inSel(i) && 'bg-primary/20 ring-2 ring-primary')}>
                    {tok}
                  </span>
                  {covering.filter((x) => x.end === i).map((x) => (
                    <sup key={`${x.start}-${x.label}`} className="mx-0.5 rounded border px-1 text-[10px] font-semibold" style={color(x.label)}>{labelOf(x.label)}</sup>
                  ))}{' '}
                </span>
              )
            })}
          </p>
        ) : <p className="text-lg leading-relaxed">{text}</p>}

        {project.task === 'ner' && sel && menu && (
          <div role="menu" style={{ left: menu.left, top: menu.top }} onMouseDown={(e) => e.stopPropagation()}
            className="absolute z-20 w-64 -translate-x-1/2 space-y-1 rounded-lg border bg-popover p-1.5 text-popover-foreground shadow-lg">
            <p className="truncate px-1.5 pt-0.5 text-xs text-muted-foreground">« {tokens.slice(Math.min(sel.a, sel.b), Math.max(sel.a, sel.b) + 1).join(' ')} »</p>
            {ordered.map((l) => (
              <button key={l.id} role="menuitem" title={l.description} onClick={() => assign(l.id)}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted">
                <span className="size-2.5 shrink-0 rounded-full" style={{ background: `hsl(${hue(l.id)} 60% 55%)` }} />
                <span className="flex-1 truncate">{l.name}</span>
                {onSelection(l) && <Check className="size-3.5 text-primary" />}
                {l.kind === 'semantic' && <span className="text-[10px] text-muted-foreground">{t('datasets.annotation.kinds.semantic.title')}</span>}
                <kbd className="rounded bg-muted px-1.5 text-xs">{ordered.indexOf(l) + 1}</kbd>
              </button>
            ))}
          </div>
        )}

        {project.task === 'qa' && <Textarea className="mt-4" placeholder={t('datasets.annotation.answerPlaceholder')} value={draft.text ?? ''} onChange={(e) => setDraft({ text: e.target.value })} />}
      </div>

      {project.task === 'classification' && (
        <div className="mt-4 space-y-2">
          <div className="grid gap-2 sm:grid-cols-2">{ordered.map(labelButton)}</div>
          <div className="space-y-1.5 pt-2">
            <label htmlFor="reason" className="text-sm font-medium">{t('datasets.annotation.reason')} <span className="font-normal text-muted-foreground">({t('datasets.annotation.optional')})</span></label>
            <Textarea id="reason" rows={2} placeholder={t('datasets.annotation.reasonPlaceholder')} value={draft.reason ?? ''} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} />
          </div>
        </div>
      )}

      {project.task === 'ner' && (
        <div className="mt-4 space-y-4">
          <p className="text-sm text-muted-foreground">{sel ? t('datasets.annotation.pickLabel') : t('datasets.annotation.selectWords')}</p>
          {(['entity', 'semantic'] as const).map((k) => {
            const list = ordered.filter((l) => (l.kind ?? 'entity') === k)
            if (!list.length) return null
            return (
              <div key={k} className="space-y-1.5">
                <h2 className="text-sm font-medium">{t(`datasets.annotation.kinds.${k}.title`)} <span className="font-normal text-muted-foreground">· {t(`datasets.annotation.kinds.${k}.hint`)}</span></h2>
                <div className="grid gap-2 sm:grid-cols-2">{list.map(labelButton)}</div>
              </div>
            )
          })}

          {!!draft.spans?.length && (
            <ul className="space-y-2 pt-2">
              {draft.spans.map((s) => (
                <li key={`${s.start}-${s.end}-${s.label}`} className="flex flex-wrap items-center gap-2 rounded-lg border p-2 text-sm">
                  <span className="rounded-full border px-2 py-0.5 text-xs font-medium" style={color(s.label)}>{labelOf(s.label)}</span>
                  <span className="max-w-xs truncate text-muted-foreground">« {tokens.slice(s.start, s.end + 1).join(' ')} »</span>
                  {needsValue(labelDef(s.label)) && (
                    <Input className={cn('h-8 w-44 font-mono', s.value && !matchesFormat(s.value, labelDef(s.label)!) && 'border-destructive')} aria-label={t('datasets.annotation.normalizedValue')}
                      placeholder={labelDef(s.label)?.formats?.[0] || t('datasets.annotation.normalizedValue')} value={s.value ?? ''} onChange={(e) => patchSpan(s, { value: e.target.value })} />
                  )}
                  {s.value && !matchesFormat(s.value, labelDef(s.label)!) && <span className="text-xs text-destructive">{t('datasets.annotation.formatMismatch', { format: labelDef(s.label)?.formats?.join(' | ') })}</span>}
                  <Input className="h-8 min-w-40 flex-1" aria-label={t('datasets.annotation.spanReason')} placeholder={t('datasets.annotation.spanReason')} value={s.reason ?? ''} onChange={(e) => patchSpan(s, { reason: e.target.value })} />
                  <button aria-label="remove" onClick={() => setDraft({ spans: draft.spans!.filter((x) => x !== s) })}><X className="size-4" /></button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="mt-6 flex items-center justify-between">
        <Button variant="ghost" onClick={() => go(Math.min(rows.length - 1, idx + 1))}><SkipForward />{t('datasets.annotation.skip')}</Button>
        <Button onClick={submit}><Check />{t('datasets.annotation.submit')} <kbd className="rounded bg-primary-foreground/20 px-1.5 text-xs">↵</kbd></Button>
      </div>
    </Container>
  )
}
