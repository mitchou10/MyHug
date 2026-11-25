import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { TaskType } from '@/features/datasets/annotation/store'
import { api } from '@/lib/api'
import type { Evaluation, Metric, Model } from '../types'
import { base, keys } from './keys'
import type { WireEvaluation, WireTaskMetrics } from './wire'

const toEvaluation = (e: WireEvaluation): Evaluation => ({
  id: e.id,
  version: e.version,
  task: e.task as TaskType,
  dataset: e.dataset,
  datasetVersion: e.dataset_version,
  split: e.split,
  inputColumn: e.input_column,
  targetColumn: e.target_column,
  items: e.items,
  source: e.source,
  status: e.status,
  error: e.error,
  results: e.results,
  hidden: e.hidden,
  shown: e.shown,
  note: e.note,
  createdByUsername: e.created_by_username,
  createdAt: e.created_at,
  finishedAt: e.finished_at,
  canEdit: e.can_edit,
})

/** The metrics of every task, defined by the platform: the same list for the page, the SDK and the evaluations. */
export function useMetrics() {
  return useQuery({
    queryKey: keys.metrics,
    queryFn: async () => {
      const found = await api<WireTaskMetrics[]>('/api/metrics')
      return new Map(found.map((t) => [t.task, t.metrics as Metric[]]))
    },
    staleTime: Infinity, // they change with a new version of the platform, not while a page is open
  })
}

/** The evaluations of a model, the newest first. What each one holds depends on who asks (see `Evaluation.results`). */
export function useEvaluations(model: Model) {
  return useQuery({
    queryKey: keys.evaluations(model.owner, model.name),
    queryFn: async () => (await api<WireEvaluation[]>(`${base(model.owner, model.name)}/evaluations`)).map(toEvaluation),
  })
}

/** Chooses the metrics the others see. */
export function useSetShown(model: Model) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, shown }: { id: string; shown: string[] }) =>
      api<WireEvaluation>(`${base(model.owner, model.name)}/evaluations/${id}/shown`, { method: 'PUT', json: { shown } }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.evaluations(model.owner, model.name) }),
  })
}

export function useDeleteEvaluation(model: Model) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`${base(model.owner, model.name)}/evaluations/${id}`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.evaluations(model.owner, model.name) }),
  })
}
