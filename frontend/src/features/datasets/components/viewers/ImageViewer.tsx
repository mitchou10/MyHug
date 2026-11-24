import type { Dataset } from '../../mockData'
import { hue, seeded } from './seed'

/** Image: a grid of thumbnails with their bounding boxes (placeholders here, the real files come from the backend). */
export function ImageViewer({ dataset: d }: { dataset: Dataset }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {d.sample.map(([file, w, h, objects]) => {
        const rnd = seeded(String(file))
        const boxes = Array.from({ length: Number(objects) }, () => ({ x: rnd() * 70, y: rnd() * 70, w: 12 + rnd() * 18, h: 12 + rnd() * 18 }))
        const a = hue(String(file))
        return (
          <figure key={String(file)} className="overflow-hidden rounded-lg border">
            <div className="relative" style={{ aspectRatio: `${w} / ${h}`, background: `linear-gradient(135deg, hsl(${a} 60% 70%), hsl(${(a + 60) % 360} 60% 45%))` }}>
              {boxes.map((b, i) => (
                <span key={i} className="absolute border-2 border-white/90 shadow" style={{ left: `${b.x}%`, top: `${b.y}%`, width: `${b.w}%`, height: `${b.h}%` }} />
              ))}
            </div>
            <figcaption className="flex justify-between px-2 py-1.5 text-xs text-muted-foreground">
              <span className="truncate">{file}</span><span>{w}×{h} · {objects} obj.</span>
            </figcaption>
          </figure>
        )
      })}
    </div>
  )
}
