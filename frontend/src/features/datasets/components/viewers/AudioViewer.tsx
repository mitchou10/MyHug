import { Pause, Play } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Dataset } from '../../mockData'
import { seeded } from './seed'

function Waveform({ id, active }: { id: string; active: boolean }) {
  const rnd = seeded(id)
  return (
    <div className="flex h-10 flex-1 items-center gap-px">
      {Array.from({ length: 70 }, (_, i) => (
        <span key={i} className={cn('w-full rounded-full', active ? 'bg-primary' : 'bg-muted-foreground/40')} style={{ height: `${15 + Math.sin(i / 6) ** 2 * 40 + rnd() * 45}%` }} />
      ))}
    </div>
  )
}

/** Audio: one row per clip with a player (play button + waveform), its label and its duration. */
export function AudioViewer({ dataset: d }: { dataset: Dataset }) {
  const [playing, setPlaying] = useState<string | null>(null)
  return (
    <div className="divide-y rounded-lg border">
      {d.sample.map(([file, label, duration]) => {
        const id = String(file)
        const on = playing === id
        return (
          <div key={id} className="flex items-center gap-3 px-4 py-3">
            <Button size="icon" variant={on ? 'default' : 'outline'} onClick={() => setPlaying(on ? null : id)} aria-label={on ? 'Pause' : 'Play'}>
              {on ? <Pause /> : <Play />}
            </Button>
            <Waveform id={id} active={on} />
            <div className="w-40 text-right text-sm">
              <div className="truncate font-medium">{label}</div>
              <div className="text-xs text-muted-foreground">{id} · {duration}s</div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
