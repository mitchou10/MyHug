import { useRef, useState, type PointerEvent } from 'react'
import { SceneGraphics } from '../components/viewers/SceneGraphics'
import { hue } from '../components/viewers/seed'
import type { ImageObject, Pt } from './store'

export type Tool = 'select' | 'polygon' | 'rect'
const stroke = (label: string, known: boolean) => (known ? `hsl(${hue(label)} 70% 42%)` : 'hsl(0 0% 45%)')
const clamp = (n: number) => Math.min(1, Math.max(0, n))

interface Props {
  file: string; width: number; height: number
  objects: ImageObject[]
  /** The polygon being drawn, point by point. */
  drawing: Pt[]
  setDrawing: (p: Pt[]) => void
  tool: Tool
  selectedId: string | null
  onSelect: (id: string | null) => void
  onChange: (objects: ImageObject[]) => void
  /** A polygon is closed (click on its first point, Enter) or a rectangle is released. */
  onFinish: (points: Pt[]) => void
  /** `segmentation` fills the regions; `detection` outlines the objects and tags them with their label; `polyline` draws open lines. */
  kind: 'detection' | 'segmentation' | 'polyline'
  labelName: (id: string) => string | undefined
}

/** The image with its polygons. Points are stored as fractions of the image, and drawn in its own pixel space. */
export function PolygonCanvas({ file, width: W, height: H, objects, drawing, setDrawing, tool, selectedId, onSelect, onChange, onFinish, kind, labelName }: Props) {
  const svg = useRef<SVGSVGElement>(null)
  const [drag, setDrag] = useState<{ id: string; i: number } | null>(null)
  const [rect, setRect] = useState<{ a: Pt; b: Pt } | null>(null)
  const [hover, setHover] = useState<Pt | null>(null)
  const r = W * 0.008 // radius of a handle
  const toPx = (p: Pt) => `${p[0] * W},${p[1] * H}`

  const toNorm = (e: PointerEvent): Pt => {
    const s = svg.current!
    const pt = s.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY
    const p = pt.matrixTransform(s.getScreenCTM()!.inverse())
    return [clamp(p.x / W), clamp(p.y / H)]
  }
  const nearFirst = (p: Pt) => kind !== 'polyline' && drawing.length >= 3 && Math.hypot((p[0] - drawing[0][0]) * W, (p[1] - drawing[0][1]) * H) < W * 0.025

  const down = (e: PointerEvent) => {
    const p = toNorm(e)
    if (tool === 'polygon') {
      if (nearFirst(p)) onFinish(drawing)
      else setDrawing([...drawing, p])
    } else if (tool === 'rect') {
      svg.current!.setPointerCapture(e.pointerId)
      setRect({ a: p, b: p })
    } else onSelect(null)
  }
  const move = (e: PointerEvent) => {
    const p = toNorm(e)
    setHover(p)
    if (rect) setRect({ ...rect, b: p })
    if (drag) onChange(objects.map((o) => (o.id === drag.id ? { ...o, points: o.points.map((q, i) => (i === drag.i ? p : q)) } : o)))
  }
  const up = () => {
    if (rect) {
      const [x1, x2] = [Math.min(rect.a[0], rect.b[0]), Math.max(rect.a[0], rect.b[0])]
      const [y1, y2] = [Math.min(rect.a[1], rect.b[1]), Math.max(rect.a[1], rect.b[1])]
      if (x2 - x1 > 0.01 && y2 - y1 > 0.01) onFinish([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
      setRect(null)
    }
    setDrag(null)
  }

  return (
    <svg ref={svg} viewBox={`0 0 ${W} ${H}`} className="block w-full touch-none select-none rounded-lg border bg-muted" style={{ cursor: tool === 'select' ? 'default' : 'crosshair' }}
      onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerLeave={() => setHover(null)}
      onDoubleClick={() => { if (kind === 'polyline' && tool === 'polygon' && drawing.length >= 3) onFinish(drawing.slice(0, -1)) /* the double click placed the last point twice */ }}>
      <SceneGraphics file={file} width={W} height={H} />

      {objects.map((o) => {
        const known = !!labelName(o.label)
        const c = stroke(o.label, known)
        const sel = o.id === selectedId
        const xs = o.points.map((p) => p[0] * W), ys = o.points.map((p) => p[1] * H)
        const tag = labelName(o.label) ?? '?'
        return (
          <g key={o.id} style={{ pointerEvents: tool === 'select' ? 'auto' : 'none' }}>
            {kind === 'polyline' ? (
              <>
                {/* A wide invisible stroke makes the thin line easy to hit. */}
                <polyline points={o.points.map(toPx).join(' ')} fill="none" stroke="transparent" strokeWidth={W * 0.012} strokeLinecap="round" onPointerDown={(e) => { e.stopPropagation(); onSelect(o.id) }} style={{ cursor: 'pointer' }} />
                <polyline points={o.points.map(toPx).join(' ')} fill="none" stroke={c} strokeWidth={sel ? 4 : 3} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" pointerEvents="none" />
              </>
            ) : (
            <polygon points={o.points.map(toPx).join(' ')} fill={c} fillOpacity={kind === 'segmentation' ? 0.45 : sel ? 0.25 : 0.12} stroke={c} strokeWidth={sel ? 3 : 2} vectorEffect="non-scaling-stroke"
              strokeLinejoin="round" onPointerDown={(e) => { e.stopPropagation(); onSelect(o.id) }} style={{ cursor: 'pointer' }} />
            )}
            {kind !== 'segmentation' && (
              <g pointerEvents="none">
                <rect x={Math.min(...xs)} y={Math.min(...ys) - H * 0.04} width={tag.length * W * 0.0105 + W * 0.014} height={H * 0.04} fill={c} />
                <text x={Math.min(...xs) + W * 0.007} y={Math.min(...ys) - H * 0.012} fill="white" fontSize={H * 0.028} fontWeight={600}>{tag}</text>
              </g>
            )}
            {sel && o.points.map((p, i) => (
              <circle key={i} cx={p[0] * W} cy={p[1] * H} r={r} fill="white" stroke={c} strokeWidth={2} vectorEffect="non-scaling-stroke" style={{ cursor: 'grab' }}
                onPointerDown={(e) => { e.stopPropagation(); svg.current!.setPointerCapture(e.pointerId); setDrag({ id: o.id, i }) }} />
            ))}
          </g>
        )
      })}

      {drawing.length > 0 && (
        <g pointerEvents="none">
          <polyline points={[...drawing, ...(hover ? [hover] : [])].map(toPx).join(' ')} fill="none" stroke="white" strokeWidth={2} strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />
          {drawing.map((p, i) => <circle key={i} cx={p[0] * W} cy={p[1] * H} r={i === 0 && drawing.length >= 3 ? r * 1.8 : r} fill={i === 0 ? 'hsl(142 70% 45%)' : 'white'} stroke="black" strokeWidth={1} vectorEffect="non-scaling-stroke" />)}
        </g>
      )}
      {rect && <rect x={Math.min(rect.a[0], rect.b[0]) * W} y={Math.min(rect.a[1], rect.b[1]) * H} width={Math.abs(rect.b[0] - rect.a[0]) * W} height={Math.abs(rect.b[1] - rect.a[1]) * H} fill="white" fillOpacity={0.15} stroke="white" strokeWidth={2} strokeDasharray="6 4" vectorEffect="non-scaling-stroke" pointerEvents="none" />}
    </svg>
  )
}
