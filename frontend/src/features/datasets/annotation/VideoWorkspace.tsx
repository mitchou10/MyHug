import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { VideoFrame } from '../components/viewers/VideoFrame'
import type { Dataset } from '../mockData'
import { TimedWorkspace, type UseMedia } from './TimedWorkspace'
import type { AnnotationProject } from './store'
import { useClockPlayer } from './useClockPlayer'
import { VIDEO_H, VIDEO_W } from './videoMock'

const FPS = 25

/** A video: its frame at the current time, a timeline without waveform, and buttons to step by one frame. */
const useVideo: UseMedia = (file, duration) => {
  const { t } = useTranslation()
  const player = useClockPlayer(duration, FPS)
  // , and . step by one frame, like in most video tools.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('textarea,input,select')) return
      if (e.key === ',') player.step(-1)
      else if (e.key === '.') player.step(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })
  return {
    clip: { duration, peaks: [] }, player, video: true,
    view: (
      <svg viewBox={`0 0 ${VIDEO_W} ${VIDEO_H}`} className="block w-full rounded-lg border bg-muted" role="img" aria-label={file}><VideoFrame file={file} t={player.time} /></svg>
    ),
    extra: (
      <div className="flex gap-1">
        <Button size="icon" variant="outline" aria-label={t('datasets.annotation.video.prevFrame')} title="," onClick={() => player.step(-1)}><ChevronLeft /></Button>
        <Button size="icon" variant="outline" aria-label={t('datasets.annotation.video.nextFrame')} title="." onClick={() => player.step(1)}><ChevronRight /></Button>
      </div>
    ),
  }
}

export function VideoWorkspace({ dataset, project }: { dataset: Dataset; project: AnnotationProject }) {
  return <TimedWorkspace dataset={dataset} project={project} useMedia={useVideo} />
}
