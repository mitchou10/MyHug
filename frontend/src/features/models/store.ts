import { useSyncExternalStore } from 'react'
import { CURRENT_USER, type TaskType } from '../datasets/annotation/store'

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

/** Temporary in-memory store of the evaluations: they move to the API with the worker (#19). `modelId` is `owner/name`. */
let state = { evaluations: [] as Evaluation[] }
const listeners = new Set<() => void>()
const set = (next: typeof state) => { state = next; listeners.forEach((l) => l()) }

export const useEvaluations = () => useSyncExternalStore((cb) => (listeners.add(cb), () => void listeners.delete(cb)), () => state)

export function addEvaluation(e: Evaluation) { set({ evaluations: [e, ...state.evaluations] }) }
export function patchEvaluation(id: string, patch: Partial<Evaluation>) { set({ evaluations: state.evaluations.map((e) => (e.id === id ? { ...e, ...patch } : e)) }) }
export function removeEvaluation(id: string) { set({ evaluations: state.evaluations.filter((e) => e.id !== id) }) }
export const getEvaluations = () => state.evaluations
export const isLauncher = (e: Evaluation) => e.startedBy === CURRENT_USER
