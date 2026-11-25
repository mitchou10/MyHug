import { AUDIO_TASKS, IMAGE_TASKS, TABULAR_TASKS, TEXT_TASKS, TIMESERIES_TASKS, VIDEO_TASKS, type TaskType } from '../datasets/annotation/store'
import type { Modality } from '../datasets/mockData'

/** The tasks of each kind of data: what a model of that kind can do. */
export const TASKS_BY_MODALITY: Record<Modality, TaskType[]> = {
  text: TEXT_TASKS,
  image: IMAGE_TASKS,
  audio: AUDIO_TASKS,
  video: VIDEO_TASKS,
  tabular: TABULAR_TASKS,
  timeseries: TIMESERIES_TASKS,
}
