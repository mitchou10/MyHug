import { useMemo } from 'react'
import type { Dataset } from '../mockData'
import { clipFor } from './audioMock'
import { TimedWorkspace, type UseMedia } from './TimedWorkspace'
import type { AnnotationProject } from './store'
import { useAudioPlayer } from './useAudioPlayer'

/** A sound: the waveform of the clip, and the Web Audio player. */
const useAudio: UseMedia = (file, duration) => {
  const clip = useMemo(() => clipFor(file, duration), [file, duration])
  return { clip, player: useAudioPlayer(clip) }
}

export function AudioWorkspace({ dataset, project }: { dataset: Dataset; project: AnnotationProject }) {
  return <TimedWorkspace dataset={dataset} project={project} useMedia={useAudio} />
}
