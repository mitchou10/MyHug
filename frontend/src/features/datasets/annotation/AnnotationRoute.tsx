import { useParams } from 'react-router'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { getDataset } from '../mockData'
import { AnnotationWorkspace } from './AnnotationWorkspace'
import { AudioWorkspace } from './AudioWorkspace'
import { VideoWorkspace } from './VideoWorkspace'
import { ImageWorkspace } from './ImageWorkspace'
import { TrackingWorkspace } from './TrackingWorkspace'
import { TimeSeriesWorkspace } from './TimeSeriesWorkspace'
import { TabularWorkspace } from './TabularWorkspace'
import { useAnnotations } from './store'

/** Picks the workspace that fits the task: a text at a time, or a grid for a table. */
export function AnnotationRoute() {
  const { owner, name, projectId } = useParams()
  const d = getDataset(owner, name)
  const project = useAnnotations().projects.find((p) => p.id === projectId)
  if (!d || !project) return <NotFoundPage />
  if (d.modality === 'timeseries') return <TimeSeriesWorkspace dataset={d} project={project} />
  if (d.modality === 'video') return project.task === 'video_tracking' ? <TrackingWorkspace dataset={d} project={project} /> : <VideoWorkspace dataset={d} project={project} />
  if (d.modality === 'audio') return <AudioWorkspace dataset={d} project={project} />
  if (d.modality === 'image') return <ImageWorkspace dataset={d} project={project} />
  return d.modality === 'tabular' ? <TabularWorkspace dataset={d} project={project} /> : <AnnotationWorkspace />
}
