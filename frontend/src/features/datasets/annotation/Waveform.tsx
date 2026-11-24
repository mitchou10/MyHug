import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { fmtTime } from './audioMock'
import type { AudioSegment } from './store'

export type AudioTool = 'select' | 'region'
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n))
const MIN = 0.05 // the shortest region, in seconds

type Drag = { kind: 'create'; t0: number; lane: number } | { kind: 'start' | 'end'; id: string } | { kind: 'move'; id: string; t0: number; start: number; end: number }

/**
 * The waveform of a clip, and under it one lane per track holding the regions.
 * Click to move the playhead; with the region tool, drag in a lane to create a region there; drag the edges of a
 * region to adjust it, or its body to move it (also to another lane). `zoom` stretches the time axis (the box scrolls).
 */
export function Waveform({ clip, time, zoom, segments, tracks, activeTrack, selectedId, tool, hueOf, tagOf, onSeek, onSelect, onCreate, onChange, onActiveTrack }: {
  clip: { duration: number; peaks: number[] }; time: number; zoom: number; segments: AudioSegment[]; tracks: string[]; activeTrack: number; selectedId: string | null; tool: AudioTool
  hueOf: (s: AudioSegment) => number | null; tagOf: (s: AudioSegment) => string
  onSeek: (t: number) => void; onSelect: (id: string | null) => void; onCreate: (start: number, end: number, track: number) => void
  onChange: (s: AudioSegment[]) => void; onActiveTrack: (i: number) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const drag = useRef<Drag | null>(null)
  const [preview, setPreview] = useState<{ a: number; b: number; lane: number } | null>(null)
  const D = clip.duration
  const pct = (t: number) => `${(t / D) * 100}%`
  const toTime = (e: PointerEvent) => {
    const r = box.current!.getBoundingClientRect()
    return clamp(((e.clientX - r.left) / r.width) * D, 0, D)
  }
  /** The lane under the pointer, or null above the lanes. */
  const laneAt = (e: PointerEvent): number | null => {
    const lanes = [...box.current!.querySelectorAll<HTMLElement>('[data-lane]')]
    const i = lanes.findIndex((l) => { const r = l.getBoundingClientRect(); return e.clientY >= r.top && e.clientY < r.bottom })
    return i < 0 ? null : i
  }
  const patch = (id: string, p: Partial<AudioSegment>) => onChange(segments.map((s) => (s.id === id ? { ...s, ...p } : s)))

  const down = (e: PointerEvent) => {
    const t = toTime(e)
    const el = e.target as HTMLElement
    const handle = el.closest<HTMLElement>('[data-handle]')
    const region = el.closest<HTMLElement>('[data-seg]')
    const lane = laneAt(e)
    box.current!.setPointerCapture(e.pointerId)
    if (lane !== null) onActiveTrack(lane)
    if (handle) { drag.current = { kind: handle.dataset.handle as 'start' | 'end', id: handle.dataset.seg! }; onSelect(handle.dataset.seg!) }
    else if (region) {
      const s = segments.find((x) => x.id === region.dataset.seg)!
      onSelect(s.id)
      drag.current = { kind: 'move', id: s.id, t0: t, start: s.start, end: s.end }
    } else if (tool === 'region') { drag.current = { kind: 'create', t0: t, lane: lane ?? activeTrack }; setPreview({ a: t, b: t, lane: lane ?? activeTrack }) }
    else { onSeek(t); onSelect(null) }
  }
  const move = (e: PointerEvent) => {
    const d = drag.current
    if (!d) return
    const t = toTime(e)
    const seg = 'id' in d ? segments.find((s) => s.id === d.id) : undefined
    if (d.kind === 'create') setPreview({ a: d.t0, b: t, lane: d.lane })
    else if (d.kind === 'start' && seg) patch(seg.id, { start: clamp(t, 0, seg.end - MIN) })
    else if (d.kind === 'end' && seg) patch(seg.id, { end: clamp(t, seg.start + MIN, D) })
    else if (d.kind === 'move') {
      const len = d.end - d.start
      const start = clamp(d.start + (t - d.t0), 0, D - len)
      const lane = laneAt(e)
      patch(d.id, { start, end: start + len, ...(lane !== null ? { track: lane } : {}) })
    }
  }
  const up = () => {
    if (drag.current?.kind === 'create' && preview && Math.abs(preview.b - preview.a) >= 0.1) onCreate(Math.min(preview.a, preview.b), Math.max(preview.a, preview.b), preview.lane)
    drag.current = null
    setPreview(null)
  }

  // Keep the playhead in view when zoomed.
  useEffect(() => {
    const sc = scroller.current, b = box.current
    if (!sc || !b || zoom <= 1) return
    const x = (time / D) * b.clientWidth
    if (x < sc.scrollLeft + 24 || x > sc.scrollLeft + sc.clientWidth - 24) sc.scrollLeft = x - sc.clientWidth / 2
  }, [time, zoom, D])

  const step = D > 60 ? 10 : D > 20 ? 5 : 2
  const ticks = Array.from({ length: Math.floor(D / step) + 1 }, (_, i) => i * step)
  const path = clip.peaks.map((p, i) => `M${i},${50 - p * 46}V${50 + p * 46}`).join('')
  const laneOf = (s: AudioSegment) => clamp(s.track ?? 0, 0, tracks.length - 1)

  return (
    <div ref={scroller} className="overflow-x-auto rounded-lg border bg-muted/30">
      <div ref={box} className="relative touch-none select-none" style={{ width: `${zoom * 100}%`, cursor: tool === 'region' ? 'crosshair' : 'pointer' }} onPointerDown={down} onPointerMove={move} onPointerUp={up}>
        <div className={`relative ${clip.peaks.length ? 'h-28' : 'h-9'}`}>
          {clip.peaks.length > 0 && <svg viewBox={`0 0 ${clip.peaks.length} 100`} preserveAspectRatio="none" className="absolute inset-0 top-5 h-[calc(100%-1.25rem)] w-full text-muted-foreground" aria-hidden>
            <path d={path} stroke="currentColor" strokeWidth={1} vectorEffect="non-scaling-stroke" fill="none" />
          </svg>}
          {ticks.map((t) => <span key={t} className="pointer-events-none absolute top-0 h-full border-l border-dashed border-border pl-1 text-[10px] text-muted-foreground" style={{ left: pct(t) }}>{t}s</span>)}
        </div>

        {tracks.map((name, i) => (
          <div key={i} data-lane={i} className={`relative h-12 border-t ${i === activeTrack ? 'bg-primary/5' : ''}`}>
            <span className="pointer-events-none sticky left-1 z-10 inline-block rounded bg-background/80 px-1.5 text-[10px] font-medium text-muted-foreground">{name}</span>
            {segments.filter((s) => laneOf(s) === i).map((s) => {
              const h = hueOf(s)
              const sel = s.id === selectedId
              const c = h === null ? 'hsl(215 20% 50%)' : `hsl(${h} 70% 50%)`
              return (
                <div key={s.id} data-seg={s.id} className="absolute top-1 bottom-1 cursor-grab rounded-sm" style={{ left: pct(s.start), width: pct(s.end - s.start), background: c.replace(')', ' / 0.3)'), border: `2px solid ${c}`, outline: sel ? `2px solid ${c}` : undefined, outlineOffset: 1 }}>
                  <span className="pointer-events-none absolute top-0 left-1 max-w-full truncate px-1 text-[10px] font-semibold" style={{ color: c }}>{tagOf(s)}</span>
                  {sel && (['start', 'end'] as const).map((side) => (
                    <span key={side} data-handle={side} data-seg={s.id} className="absolute top-0 bottom-0 w-3 cursor-ew-resize" style={side === 'start' ? { left: -8 } : { right: -8 }}>
                      <span className="absolute top-1/2 left-1/2 h-6 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded bg-white shadow ring-1 ring-black/30" />
                    </span>
                  ))}
                </div>
              )
            })}
            {preview && preview.lane === i && <div className="pointer-events-none absolute top-1 bottom-1 border-2 border-dashed border-primary bg-primary/15" style={{ left: pct(Math.min(preview.a, preview.b)), width: pct(Math.abs(preview.b - preview.a)) }} />}
          </div>
        ))}

        <div className="pointer-events-none absolute top-0 bottom-0 w-0.5 bg-primary" style={{ left: pct(time) }}>
          <span className="absolute top-0 left-1 rounded bg-primary px-1 text-[10px] whitespace-nowrap text-primary-foreground">{fmtTime(time)}</span>
        </div>
      </div>
    </div>
  )
}
