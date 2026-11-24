import { seeded } from '@/features/datasets/components/viewers/seed'
import type { TaskType } from '@/features/datasets/annotation/store'

/**
 * The important metrics of each kind of task. An evaluation computes all of them; the person who launches it decides
 * which ones are shown. `higher`: whether a higher value is better; `scale`: the order of magnitude of an error, for the mock.
 */
export interface Metric { id: string; name: string; higher: boolean; primary?: boolean; scale?: number }

const m = (id: string, name: string, higher = true, extra: Partial<Metric> = {}): Metric => ({ id, name, higher, ...extra })

const CLASSIFICATION = [m('accuracy', 'Accuracy', true, { primary: true }), m('precision', 'Precision'), m('recall', 'Recall'), m('f1', 'F1'), m('auc', 'AUC')]
const SPANS = [m('f1', 'F1', true, { primary: true }), m('precision', 'Precision'), m('recall', 'Recall'), m('exact_match', 'Exact match')]
const TEMPORAL = [m('f1', 'F1', true, { primary: true }), m('precision', 'Precision'), m('recall', 'Recall'), m('iou_temporal', 'IoU temporel'), m('boundary_error', 'Erreur de frontière (s)', false, { scale: 2 })]
const CAPTION = [m('bleu', 'BLEU', true, { primary: true }), m('rouge_l', 'ROUGE-L'), m('cider', 'CIDEr'), m('meteor', 'METEOR')]

export const METRICS: Partial<Record<TaskType, Metric[]>> = {
  classification: CLASSIFICATION, image_classification: CLASSIFICATION, audio_classification: CLASSIFICATION, video_classification: CLASSIFICATION, timeseries_classification: CLASSIFICATION, row_label: CLASSIFICATION,
  ner: SPANS,
  qa: [m('exact_match', 'Exact match', true, { primary: true }), m('f1', 'F1')],
  regression: [m('mae', 'MAE', false, { primary: true, scale: 8 }), m('rmse', 'RMSE', false, { scale: 10 }), m('r2', 'R²'), m('mape', 'MAPE (%)', false, { scale: 20 })],
  cell_review: [m('f1', 'F1', true, { primary: true }), m('precision', 'Precision'), m('recall', 'Recall')],
  column_schema: [m('accuracy', 'Accuracy', true, { primary: true }), m('f1', 'F1')],
  image_detection: [m('map50', 'mAP@50', true, { primary: true }), m('map50_95', 'mAP@50:95'), m('precision', 'Precision'), m('recall', 'Recall')],
  image_polyline: [m('f1', 'F1', true, { primary: true }), m('precision', 'Precision'), m('recall', 'Recall'), m('chamfer', 'Distance de Chamfer', false, { scale: 6 })],
  image_segmentation: [m('miou', 'mIoU', true, { primary: true }), m('dice', 'Dice'), m('pixel_accuracy', 'Précision par pixel'), m('boundary_f1', 'F1 de contour')],
  image_keypoints: [m('pck', 'PCK', true, { primary: true }), m('oks_ap', 'AP (OKS)'), m('mpjpe', 'MPJPE (px)', false, { scale: 12 })],
  image_caption: CAPTION, audio_caption: CAPTION, video_caption: CAPTION, timeseries_caption: CAPTION,
  image_vqa: [m('vqa_accuracy', 'Précision VQA', true, { primary: true }), m('exact_match', 'Exact match'), m('f1', 'F1')],
  audio_segments: TEMPORAL, video_segments: TEMPORAL, timeseries_segments: TEMPORAL,
  audio_transcription: [m('wer', 'WER', false, { primary: true, scale: 0.5 }), m('cer', 'CER', false, { scale: 0.3 }), m('ser', 'SER (phrases)', false, { scale: 0.8 })],
  video_tracking: [m('mota', 'MOTA', true, { primary: true }), m('idf1', 'IDF1'), m('hota', 'HOTA'), m('id_switches', 'Changements d’identité', false, { scale: 40 })],
}

export const metricsFor = (task: TaskType): Metric[] => METRICS[task] ?? [m('accuracy', 'Accuracy', true, { primary: true })]
export const primaryOf = (task: TaskType) => metricsFor(task).find((x) => x.primary) ?? metricsFor(task)[0]
/** The metrics shown unless the person who launches the evaluation chooses otherwise: the main one and the next. */
export const defaultShown = (task: TaskType) => metricsFor(task).slice(0, 2).map((x) => x.id)

/** Every metric of a kind of task, for a model on a dataset (simulated: plausible and repeatable). */
export function computeMetrics(task: TaskType, model: string, dataset: string, split: string, quality: number): Record<string, number> {
  const rnd = seeded(`${model}:${task}:${dataset}:${split}`)
  return Object.fromEntries(metricsFor(task).map((x) => {
    const v = x.higher ? Math.min(0.995, Math.max(0.05, quality - 0.14 + rnd() * 0.2)) : (1 - quality) * (0.5 + rnd() * 0.9) * (x.scale ?? 1)
    return [x.id, Number(v.toFixed(x.scale && x.scale >= 10 ? 1 : 3))]
  }))
}
