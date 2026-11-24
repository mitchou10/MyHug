import { useSyncExternalStore } from 'react'
import { MODELS as ANNOTATION_MODELS } from '../datasets/annotation/models'
import { itemCount } from '../datasets/annotation/preannotate'
import { CURRENT_USER, type TaskType } from '../datasets/annotation/store'
import { DATASETS } from '../datasets/mockData'
import { computeMetrics, defaultShown, metricsFor } from './metrics'
import { MODEL_HUB, type Model } from './mockData'

/**
 * An evaluation of a model, for one of its tasks, on a part of a dataset. All the metrics of the task are computed;
 * `shown` are the ones the person who launched it chose to show to the others.
 */
export interface Evaluation {
  id: string; modelId: string; version: string; task: TaskType
  dataset: string; split: 'test' | 'validation'
  startedBy: string; startedAt: number
  status: 'running' | 'done' | 'stopped'
  total: number; processed: number
  results?: Record<string, number>
  shown: string[]
}

/** Some finished evaluations, so that models can be compared before anybody has launched one. */
function seedEvaluations(): Evaluation[] {
  return MODEL_HUB.flatMap((m) => m.tasks.slice(0, 2).flatMap((task) => {
    const quality = ANNOTATION_MODELS.find((x) => x.id === m.name)?.quality ?? 0.7
    const sets = DATASETS.filter((d) => m.inputs.includes(d.modality)).sort((a, b) => Number(m.trainedOn.includes(`${b.owner}/${b.name}`)) - Number(m.trainedOn.includes(`${a.owner}/${a.name}`))).slice(0, 2)
    return sets.map((d, i): Evaluation => {
      const key = `${d.owner}/${d.name}`
      return {
        id: `e-${m.name}-${task}-${i}`, modelId: m.id, version: m.version, task, dataset: key, split: 'test', startedBy: m.owner, startedAt: Date.parse('2026-11-08') + i * 86_400_000,
        status: 'done', total: itemCount(d), processed: itemCount(d), results: computeMetrics(task, m.name, key, 'test', quality),
        // Some authors show everything, most show the main metrics.
        shown: i === 0 && m.name.length % 2 === 0 ? metricsFor(task).map((x) => x.id) : defaultShown(task),
      }
    })
  }))
}

/** Temporary in-memory store: replaced by the API once the backend handles models. */
let state = { models: MODEL_HUB, liked: new Set<string>(), evaluations: seedEvaluations() }
const listeners = new Set<() => void>()
const set = (next: typeof state) => { state = next; listeners.forEach((l) => l()) }

export const useModels = () => useSyncExternalStore((cb) => (listeners.add(cb), () => void listeners.delete(cb)), () => state)

export const findModel = (models: Model[], owner?: string, name?: string) => models.find((m) => m.owner === owner && m.name === name)

export function addModel(m: Model) { set({ ...state, models: [m, ...state.models] }) }
export function toggleLike(id: string) {
  const liked = new Set(state.liked)
  if (liked.has(id)) liked.delete(id); else liked.add(id)
  set({ ...state, liked })
}

export function addEvaluation(e: Evaluation) { set({ ...state, evaluations: [e, ...state.evaluations] }) }
export function patchEvaluation(id: string, patch: Partial<Evaluation>) { set({ ...state, evaluations: state.evaluations.map((e) => (e.id === id ? { ...e, ...patch } : e)) }) }
export function removeEvaluation(id: string) { set({ ...state, evaluations: state.evaluations.filter((e) => e.id !== id) }) }
export const getEvaluations = () => state.evaluations
export const isLauncher = (e: Evaluation) => e.startedBy === CURRENT_USER
