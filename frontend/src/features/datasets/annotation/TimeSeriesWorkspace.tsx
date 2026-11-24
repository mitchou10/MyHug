import { useMemo, useState } from 'react'
import type { Dataset } from '../mockData'
import { dateAt, seriesFor } from './seriesMock'
import { TimedWorkspace, type UseMedia } from './TimedWorkspace'
import type { AnnotationProject } from './store'
import type { Player } from './useAudioPlayer'

/**
 * A series is drawn as a line on the timeline of the timed workspace (regions, tracks, labels, texts and scores work
 * as for a sound). There is nothing to play: the player is a cursor, moved by clicking the chart.
 */
const useSeries: UseMedia = (id, duration, d) => {
  const item = d.collection?.find((c) => c.id === id)
  const start = item?.start ?? '2023-01-01'
  const clip = useMemo(() => {
    const values = seriesFor(id, (item?.points ?? duration + 1))
    const lo = Math.min(...values), hi = Math.max(...values)
    return { duration, peaks: values.map((v) => (v - lo) / (hi - lo || 1)), line: true, format: (t: number) => dateAt(start, t) }
  }, [id, duration, item?.points, start])
  const [time, setTime] = useState(0)
  const player: Player = { playing: false, time, speed: 1, toggle: () => {}, pause: () => {}, playRange: () => {}, setSpeed: () => {}, seek: (t) => setTime(Math.min(Math.max(0, t), duration)) }
  return { clip, player, still: true, format: clip.format, step: 1 }
}

export function TimeSeriesWorkspace({ dataset, project }: { dataset: Dataset; project: AnnotationProject }) {
  return <TimedWorkspace dataset={dataset} project={project} useMedia={useSeries} />
}
