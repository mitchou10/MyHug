import type { ModelFilters } from '../types'

/** The keys of the cache, in one place: a change invalidates the keys it touches. */
export const keys = {
  all: ['models'] as const,
  lists: ['models', 'list'] as const,
  list: (filters: ModelFilters) => ['models', 'list', filters] as const,
  one: (owner: string, name: string) => ['models', 'one', owner, name] as const,
  versions: (owner: string, name: string) => ['models', 'versions', owner, name] as const,
  version: (owner: string, name: string, number: number) => ['models', 'version', owner, name, number] as const,
  members: (owner: string, name: string) => ['models', 'members', owner, name] as const,
}

export const base = (owner: string, name: string) => `/api/models/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`
