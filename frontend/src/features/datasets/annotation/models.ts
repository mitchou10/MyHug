import type { TaskType } from './store'

/**
 * The models that can pre-annotate. Each one works for some kinds of tasks (and so some kinds of data): a model that
 * finds entities in a text cannot draw boxes on an image. The real list will come from the backend, with costs and versions.
 * `quality` and `msPerItem` only drive the mock model (how sure it sounds, how fast it goes).
 */
export interface ModelInfo { id: string; tasks: TaskType[]; quality: number; msPerItem: number }

export const MODELS: ModelInfo[] = [
  // Text
  { id: 'sentiment-fr-v2', tasks: ['classification'], quality: 0.9, msPerItem: 900 },
  { id: 'zero-shot-text', tasks: ['classification', 'regression'], quality: 0.55, msPerItem: 400 },
  { id: 'ner-fr-v1', tasks: ['ner'], quality: 0.8, msPerItem: 700 },
  { id: 'ner-legal-v1', tasks: ['ner'], quality: 0.9, msPerItem: 1200 },
  { id: 'qa-extractive-v1', tasks: ['qa'], quality: 0.7, msPerItem: 800 },
  // Tabular
  { id: 'tabular-quality-v1', tasks: ['row_label', 'cell_review'], quality: 0.8, msPerItem: 500 },
  { id: 'schema-guesser-v1', tasks: ['column_schema'], quality: 0.75, msPerItem: 600 },
  { id: 'regressor-base-v1', tasks: ['regression'], quality: 0.65, msPerItem: 450 },
  // Image
  { id: 'detector-v3', tasks: ['image_detection', 'image_polyline'], quality: 0.85, msPerItem: 800 },
  { id: 'segmenter-sam-lite', tasks: ['image_segmentation', 'image_detection'], quality: 0.8, msPerItem: 1100 },
  { id: 'pose-v1', tasks: ['image_keypoints'], quality: 0.75, msPerItem: 900 },
  { id: 'scene-clip-v1', tasks: ['image_classification'], quality: 0.85, msPerItem: 500 },
  { id: 'captioner-v2', tasks: ['image_caption', 'image_vqa'], quality: 0.7, msPerItem: 1200 },
  // Audio
  { id: 'birdnet-lite', tasks: ['audio_classification', 'audio_segments'], quality: 0.8, msPerItem: 800 },
  { id: 'diarizer-v1', tasks: ['audio_segments'], quality: 0.75, msPerItem: 1000 },
  { id: 'speech-to-text-v3', tasks: ['audio_transcription'], quality: 0.9, msPerItem: 1300 },
  { id: 'audio-caption-v1', tasks: ['audio_caption'], quality: 0.6, msPerItem: 900 },
  // Video
  { id: 'action-seg-v1', tasks: ['video_segments', 'video_classification'], quality: 0.75, msPerItem: 1000 },
  { id: 'tracker-v2', tasks: ['video_tracking'], quality: 0.85, msPerItem: 1400 },
  { id: 'video-caption-v1', tasks: ['video_caption'], quality: 0.6, msPerItem: 1100 },
  // Time series
  { id: 'anomaly-v1', tasks: ['timeseries_segments'], quality: 0.8, msPerItem: 600 },
  { id: 'ts-classifier-v1', tasks: ['timeseries_classification', 'timeseries_caption'], quality: 0.7, msPerItem: 600 },
  { id: 'forecaster-v1', tasks: ['regression'], quality: 0.7, msPerItem: 700 },
]

/** The models that can pre-annotate a kind of task. */
export const modelsFor = (task: TaskType) => MODELS.filter((m) => m.tasks.includes(task))
export const modelInfo = (id: string) => MODELS.find((m) => m.id === id)
