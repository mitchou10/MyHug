import type { Dataset } from '../mockData'
import { AudioViewer } from './viewers/AudioViewer'
import { ImageViewer } from './viewers/ImageViewer'
import { TabularViewer } from './viewers/TabularViewer'
import { TextViewer } from './viewers/TextViewer'
import { TimeSeriesViewer } from './viewers/TimeSeriesViewer'
import { VideoViewer } from './viewers/VideoViewer'

const VIEWERS = {
  text: TextViewer,
  image: ImageViewer,
  audio: AudioViewer,
  video: VideoViewer,
  tabular: TabularViewer,
  timeseries: TimeSeriesViewer,
} satisfies Record<Dataset['modality'], unknown>

/** The preview of a dataset: each modality has its own view, like the Hugging Face viewer. */
export function DatasetViewer({ dataset }: { dataset: Dataset }) {
  const Viewer = VIEWERS[dataset.modality]
  return <Viewer dataset={dataset} />
}
