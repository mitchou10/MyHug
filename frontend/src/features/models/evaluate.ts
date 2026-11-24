import { ANNOTATION_QUALITY } from './quality'
import { itemCount } from '../datasets/annotation/preannotate'
import { CURRENT_USER } from '../datasets/annotation/store'
import { DATASETS } from '../datasets/mockData'
import { computeMetrics } from './metrics'
import { addEvaluation, getEvaluations, patchEvaluation, removeEvaluation, type Evaluation } from './store'

const timers = new Map<string, ReturnType<typeof setInterval>>()
const halt = (id: string) => { const t = timers.get(id); if (t) clearInterval(t); timers.delete(id) }
const uid = () => Math.random().toString(36).slice(2, 8)

/** Goes through one more item. At the end, every metric of the task is computed, whatever the author chose to show. */
function step(id: string) {
  const e = getEvaluations().find((x) => x.id === id)
  if (!e || e.status !== 'running') return halt(id)
  const processed = Math.min(e.total, e.processed + Math.max(1, Math.ceil(e.total / 30)))
  if (processed < e.total) return patchEvaluation(id, { processed })
  halt(id)
  const name = e.modelId.split('/')[1]
  patchEvaluation(id, { processed, status: 'done', results: computeMetrics(e.task, name, e.dataset, e.split, ANNOTATION_QUALITY(name)) })
}

/** Launches an evaluation. `shown` is what the others will see of it. */
export function startEvaluation(p: Pick<Evaluation, 'modelId' | 'version' | 'task' | 'dataset' | 'split' | 'shown'>) {
  const d = DATASETS.find((x) => `${x.owner}/${x.name}` === p.dataset)
  if (!d) return
  const e: Evaluation = { ...p, id: `e-${uid()}`, startedBy: CURRENT_USER, startedAt: Date.now(), status: 'running', total: Math.max(1, itemCount(d)), processed: 0 }
  addEvaluation(e)
  timers.set(e.id, setInterval(() => step(e.id), 350))
}
export function stopEvaluation(id: string) { halt(id); patchEvaluation(id, { status: 'stopped' }) }
export function deleteEvaluation(id: string) { halt(id); removeEvaluation(id) }
