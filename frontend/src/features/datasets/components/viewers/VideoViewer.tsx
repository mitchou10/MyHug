import { Play } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { Dataset } from '../../mockData'
import { hue } from './seed'

const mmss = (s: number) => `0:${String(Math.round(s)).padStart(2, '0')}`

/** Video: 16/9 thumbnails with a play button, the duration and the action label. */
export function VideoViewer({ dataset: d }: { dataset: Dataset }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {d.sample.map(([clip, action, duration, fps]) => {
        const a = hue(String(clip))
        return (
          <figure key={String(clip)} className="overflow-hidden rounded-lg border">
            <div className="relative aspect-video" style={{ background: `linear-gradient(135deg, hsl(${a} 45% 35%), hsl(${(a + 80) % 360} 50% 20%))` }}>
              <span className="absolute inset-0 m-auto flex size-12 items-center justify-center rounded-full bg-white/90 text-black"><Play className="size-5" /></span>
              <span className="absolute right-2 bottom-2 rounded bg-black/70 px-1.5 py-0.5 text-xs text-white">{mmss(Number(duration))}</span>
            </div>
            <figcaption className="flex items-center justify-between px-3 py-2 text-sm">
              <span className="truncate text-muted-foreground">{clip} · {fps} fps</span>
              <Badge variant="secondary">{action}</Badge>
            </figcaption>
          </figure>
        )
      })}
    </div>
  )
}
