import { useSyncExternalStore } from 'react'
import { CURRENT_USER } from '../datasets/annotation/store'

/** Temporary in-memory store: replaced by the API once the backend handles collections. */
export type ItemType = 'dataset' | 'model'
/** What a collection holds: a dataset or a model, as `owner/name`, and the author's note on why it is there. */
export interface CollectionItem { type: ItemType; ref: string; note?: string }
export interface Collection {
  id: string; owner: string; slug: string; title: string; description: string
  visibility: 'public' | 'private'
  items: CollectionItem[]
  likes: number; updatedAt: string
}

const today = () => new Date().toISOString().slice(0, 10)

let state = {
  liked: new Set<string>(),
  collections: [
    {
      id: 'c1', owner: 'mitchou', slug: 'sentiment-francais', title: 'Analyse de sentiment en français', visibility: 'public', likes: 24, updatedAt: '2026-11-20',
      description: 'Le jeu de données de critiques et les modèles qui en tirent un sentiment, du plus rapide au plus précis.',
      items: [
        { type: 'dataset', ref: 'mitchou/movie-reviews-fr', note: 'Le point de départ : 120 000 critiques annotées.' },
        { type: 'model', ref: 'mitchou/sentiment-fr-v2', note: 'Le plus précis, un peu lent.' },
        { type: 'model', ref: 'lab/zero-shot-text', note: 'Pour démarrer sans données : rapide, moins précis.' },
      ],
    },
    {
      id: 'c2', owner: 'lab', slug: 'vision-routiere', title: 'Vision routière', visibility: 'public', likes: 41, updatedAt: '2026-11-18',
      description: 'Tout pour détecter et classer les panneaux et les scènes de route.',
      items: [
        { type: 'dataset', ref: 'mitchou/street-signs' },
        { type: 'model', ref: 'lab/detector-v3', note: 'Détection des panneaux.' },
        { type: 'model', ref: 'lab/segmenter-sam-lite', note: 'Pour détourer la route et ses abords.' },
        { type: 'model', ref: 'lab/scene-clip-v1' },
      ],
    },
    {
      id: 'c3', owner: 'mitchou', slug: 'parole-centre-appel', title: 'Parole en centre d’appel', visibility: 'private', likes: 0, updatedAt: '2026-11-22',
      description: 'En cours de préparation : transcription et séparation des locuteurs sur les appels.',
      items: [
        { type: 'dataset', ref: 'lab/call-center-fr' },
        { type: 'model', ref: 'lab/speech-to-text-v3' },
        { type: 'model', ref: 'lab/diarizer-v1', note: 'À comparer avec la transcription seule.' },
      ],
    },
  ] as Collection[],
}
const listeners = new Set<() => void>()
const set = (next: typeof state) => { state = next; listeners.forEach((l) => l()) }
const patch = (id: string, fn: (c: Collection) => Collection) => set({ ...state, collections: state.collections.map((c) => (c.id === id ? { ...fn(c), updatedAt: today() } : c)) })

export const useCollections = () => useSyncExternalStore((cb) => (listeners.add(cb), () => void listeners.delete(cb)), () => state)

/** A private collection is seen by its owner only. */
export const canSee = (c: Collection) => c.visibility === 'public' || c.owner === CURRENT_USER
export const isMine = (c: Collection) => c.owner === CURRENT_USER
export const findCollection = (list: Collection[], owner?: string, slug?: string) => list.find((c) => c.owner === owner && c.slug === slug)
export const hasItem = (c: Collection, type: ItemType, ref: string) => c.items.some((i) => i.type === type && i.ref === ref)

const slugify = (title: string) => title.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'collection'

export function createCollection(p: { title: string; description: string; visibility: Collection['visibility']; items?: CollectionItem[] }): Collection {
  const base = slugify(p.title)
  let slug = base, n = 2
  while (state.collections.some((c) => c.owner === CURRENT_USER && c.slug === slug)) slug = `${base}-${n++}`
  const c: Collection = { id: `c-${Math.random().toString(36).slice(2, 8)}`, owner: CURRENT_USER, slug, title: p.title.trim(), description: p.description.trim(), visibility: p.visibility, items: p.items ?? [], likes: 0, updatedAt: today() }
  set({ ...state, collections: [c, ...state.collections] })
  return c
}
export const updateCollection = (id: string, p: Partial<Pick<Collection, 'title' | 'description' | 'visibility'>>) => patch(id, (c) => ({ ...c, ...p }))
export const deleteCollection = (id: string) => set({ ...state, collections: state.collections.filter((c) => c.id !== id) })
export const addItem = (id: string, item: CollectionItem) => patch(id, (c) => (hasItem(c, item.type, item.ref) ? c : { ...c, items: [...c.items, item] }))
export const removeItem = (id: string, type: ItemType, ref: string) => patch(id, (c) => ({ ...c, items: c.items.filter((i) => !(i.type === type && i.ref === ref)) }))
export const setNote = (id: string, type: ItemType, ref: string, note: string) => patch(id, (c) => ({ ...c, items: c.items.map((i) => (i.type === type && i.ref === ref ? { ...i, note: note || undefined } : i)) }))
export function moveItem(id: string, index: number, dir: -1 | 1) {
  patch(id, (c) => {
    const to = index + dir
    if (to < 0 || to >= c.items.length) return c
    const items = [...c.items]
    ;[items[index], items[to]] = [items[to], items[index]]
    return { ...c, items }
  })
}
export function toggleLike(id: string) {
  const liked = new Set(state.liked)
  if (liked.has(id)) liked.delete(id); else liked.add(id)
  set({ ...state, liked })
}
