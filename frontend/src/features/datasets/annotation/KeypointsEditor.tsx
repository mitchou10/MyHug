import { Check, Plus, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { SceneGraphics } from '../components/viewers/SceneGraphics'
import { hue } from '../components/viewers/seed'
import type { Answer, AnnotationProject, KeypointInstance, Pt } from './store'

const uid = () => Math.random().toString(36).slice(2, 8)
const clamp = (n: number) => Math.min(1, Math.max(0, n))
const dot = (label: string) => `hsl(${hue(label)} 75% 48%)`

/**
 * Keypoints: the labels of the task are the points to place, in order, on each instance (a person, a sign…).
 * A click places the next missing point of the active instance; a placed point can be dragged or marked hidden.
 */
export function KeypointsEditor({ file, W, H, project, draft, setDraft, footer }: {
  file: string; W: number; H: number; project: AnnotationProject; draft: Answer; setDraft: (a: Answer) => void; footer: ReactNode
}) {
  const { t } = useTranslation()
  const labels = project.labels
  const instances = draft.instances ?? []
  const svg = useRef<SVGSVGElement>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [chosen, setChosen] = useState<string | null>(null)
  const [drag, setDrag] = useState<{ inst: string; label: string } | null>(null)

  const inst = instances.find((i) => i.id === activeId) ?? instances[instances.length - 1]
  const missing = (i?: KeypointInstance) => labels.find((l) => !i?.points.some((p) => p.label === l.id))?.id ?? null
  const full = !!inst && missing(inst) === null
  const target = chosen ?? missing(inst) ?? labels[0]?.id
  const r = W * 0.009

  const setInstances = (next: KeypointInstance[]) => setDraft({ ...draft, instances: next })
  const patch = (id: string, fn: (i: KeypointInstance) => KeypointInstance) => setInstances(instances.map((i) => (i.id === id ? fn(i) : i)))
  const toNorm = (e: PointerEvent): Pt => {
    const s = svg.current!
    const pt = s.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY
    const p = pt.matrixTransform(s.getScreenCTM()!.inverse())
    return [clamp(p.x / W), clamp(p.y / H)]
  }

  const place = (point: Pt) => {
    if (!target) return
    // A full instance: the next click starts a new one (unless a point was chosen on purpose, to move it).
    if (!inst || (full && !chosen)) {
      const n: KeypointInstance = { id: uid(), points: [{ label: labels[0].id, point }] }
      setInstances([...instances, n]); setActiveId(n.id); setChosen(null)
      return
    }
    patch(inst.id, (i) => ({ ...i, points: [...i.points.filter((p) => p.label !== target), { label: target, point, occluded: i.points.find((p) => p.label === target)?.occluded }] }))
    setChosen(null)
  }
  const newInstance = () => { const n: KeypointInstance = { id: uid(), points: [] }; setInstances([...instances, n]); setActiveId(n.id); setChosen(null) }
  const removePoint = (label: string) => inst && patch(inst.id, (i) => ({ ...i, points: i.points.filter((p) => p.label !== label) }))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('textarea,input')) return
      const n = Number(e.key)
      if (n >= 1 && n <= labels.length) setChosen(labels[n - 1].id)
      else if (e.key === 'n') newInstance()
      else if (e.key === 'Escape') setChosen(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const move = (e: PointerEvent) => {
    if (!drag) return
    const p = toNorm(e)
    patch(drag.inst, (i) => ({ ...i, points: i.points.map((q) => (q.label === drag.label ? { ...q, point: p } : q)) }))
  }

  return (
    <div className="mt-4 grid items-start gap-4 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-2">
        <svg ref={svg} viewBox={`0 0 ${W} ${H}`} className="block w-full touch-none select-none rounded-lg border bg-muted" style={{ cursor: 'crosshair' }}
          onPointerDown={(e) => place(toNorm(e))} onPointerMove={move} onPointerUp={() => setDrag(null)}>
          <SceneGraphics file={file} width={W} height={H} />
          {instances.map((it, n) => {
            const ordered = labels.flatMap((l) => it.points.filter((p) => p.label === l.id))
            const on = it.id === inst?.id
            return (
              <g key={it.id} opacity={on ? 1 : 0.7}>
                {ordered.length > 1 && <polyline points={ordered.map((p) => `${p.point[0] * W},${p.point[1] * H}`).join(' ')} fill="none" stroke="white" strokeOpacity={0.7} strokeWidth={2} strokeDasharray="5 4" vectorEffect="non-scaling-stroke" pointerEvents="none" />}
                {it.points.map((p) => (
                  <g key={p.label}>
                    <circle cx={p.point[0] * W} cy={p.point[1] * H} r={on ? r * 1.2 : r} fill={p.occluded ? 'transparent' : dot(p.label)} stroke={p.occluded ? dot(p.label) : 'white'} strokeWidth={p.occluded ? 3 : 2} strokeDasharray={p.occluded ? '3 2' : undefined} vectorEffect="non-scaling-stroke"
                      style={{ cursor: 'grab' }} onPointerDown={(e) => { e.stopPropagation(); svg.current!.setPointerCapture(e.pointerId); setActiveId(it.id); setDrag({ inst: it.id, label: p.label }) }} />
                    {on && <text x={p.point[0] * W + r * 1.8} y={p.point[1] * H + r * 0.6} fontSize={H * 0.028} fontWeight={600} fill="white" stroke="black" strokeWidth={H * 0.006} paintOrder="stroke" pointerEvents="none">{labels.find((l) => l.id === p.label)?.name ?? '?'}</text>}
                  </g>
                ))}
                {ordered[0] && <text x={ordered[0].point[0] * W} y={ordered[0].point[1] * H - r * 2} textAnchor="middle" fontSize={H * 0.028} fontWeight={700} fill="white" stroke="black" strokeWidth={H * 0.006} paintOrder="stroke" pointerEvents="none">{n + 1}</text>}
              </g>
            )
          })}
        </svg>
        <p className="text-xs text-muted-foreground">{inst ? (full && !chosen ? t('datasets.annotation.image.kp.full') : t('datasets.annotation.image.kp.hint')) : t('datasets.annotation.image.kp.none')}</p>
        <p className="text-xs text-muted-foreground">{file} · {W}×{H} · {t('datasets.annotation.image.emptyScene')}</p>
      </div>

      <aside className="space-y-4 rounded-lg border p-4 lg:sticky lg:top-4">
        <div className="space-y-1.5">
          <div className="flex flex-wrap gap-1.5">
            {instances.map((it, n) => (
              <Button key={it.id} size="sm" variant={it.id === inst?.id ? 'default' : 'outline'} onClick={() => { setActiveId(it.id); setChosen(null) }}>
                {t('datasets.annotation.image.kp.instance', { n: n + 1 })} <span className="opacity-70">{it.points.length}/{labels.length}</span>
              </Button>
            ))}
            <Button size="sm" variant="ghost" onClick={newInstance}><Plus />{t('datasets.annotation.image.kp.newInstance')} <kbd className="rounded bg-muted px-1 text-[10px] uppercase">n</kbd></Button>
          </div>
          {inst && <Button size="sm" variant="ghost" className="text-destructive" onClick={() => { setInstances(instances.filter((i) => i.id !== inst.id)); setActiveId(null) }}><Trash2 />{t('datasets.annotation.image.kp.deleteInstance')}</Button>}
        </div>

        <div className="grid gap-1.5">
          {labels.map((l, i) => {
            const placed = inst?.points.find((p) => p.label === l.id)
            const isTarget = target === l.id
            return (
              <div key={l.id} className={cn('rounded-lg border p-1.5', isTarget && 'ring-2 ring-primary')}>
                <button type="button" title={l.description} onClick={() => setChosen(l.id)} className="flex w-full items-center gap-2 text-left text-sm">
                  <kbd className="rounded bg-muted px-1.5 text-xs">{i + 1}</kbd>
                  <span className="size-2.5 shrink-0 rounded-full" style={{ background: dot(l.id) }} />
                  <span className="flex flex-1 flex-col"><span>{l.name}</span>{l.description && <span className="text-xs text-muted-foreground">{l.description}</span>}</span>
                  {placed && <Check className="size-4 text-primary" />}
                </button>
                {placed && (
                  <div className="mt-1 flex items-center gap-3 pl-8 text-xs">
                    <label className="flex items-center gap-1.5">
                      <input type="checkbox" className="accent-primary" checked={!!placed.occluded} onChange={(e) => patch(inst!.id, (it) => ({ ...it, points: it.points.map((p) => (p.label === l.id ? { ...p, occluded: e.target.checked } : p)) }))} />
                      {t('datasets.annotation.image.kp.occluded')}
                    </label>
                    <button type="button" aria-label={t('datasets.annotation.image.kp.remove')} className="ml-auto text-muted-foreground hover:text-foreground" onClick={() => removePoint(l.id)}><X className="size-3.5" /></button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
        {inst && !full && target && <p className="text-xs text-muted-foreground">{t('datasets.annotation.image.kp.next', { label: labels.find((l) => l.id === target)?.name })}</p>}
        {footer}
      </aside>
    </div>
  )
}
