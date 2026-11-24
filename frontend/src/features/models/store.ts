import { useSyncExternalStore } from 'react'
import { MODEL_HUB, type Model } from './mockData'

/** Temporary in-memory store: replaced by the API once the backend handles models. */
let state = { models: MODEL_HUB, liked: new Set<string>() }
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
