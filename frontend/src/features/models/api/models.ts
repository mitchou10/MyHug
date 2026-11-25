import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Member, Model, ModelFilters } from '../types'
import { base, keys } from './keys'
import { toMember, toModel } from './mappers'
import type { WireMember, WireModel, WireModelSummary, WirePage } from './wire'

export const PAGE_SIZE = 12

function address(filters: ModelFilters, offset: number) {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset), sort: filters.sort })
  if (filters.q.trim()) params.set('q', filters.q.trim())
  if (filters.modality) params.set('modality', filters.modality)
  if (filters.task) params.set('task', filters.task)
  return `/api/models?${params}`
}

/** The models I can see, a page at a time: `loadMore` adds the next one. The filters are the server's. */
export function useModelList(filters: ModelFilters, enabled = true) {
  const query = useInfiniteQuery({
    queryKey: keys.list(filters),
    queryFn: ({ pageParam }) => api<WirePage<WireModelSummary>>(address(filters, pageParam)),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.limit : undefined),
    enabled,
  })
  return {
    items: query.data?.pages.flatMap((page) => page.items.map(toModel)) ?? [],
    total: query.data?.pages[0]?.total ?? 0,
    isLoading: query.isPending && enabled,
    isError: query.isError,
    error: query.error,
    hasMore: query.hasNextPage,
    loadMore: () => void query.fetchNextPage(),
    loadingMore: query.isFetchingNextPage,
  }
}

/** One model. A private one that is not mine fails with a 404, like one that does not exist. */
export function useModel(owner: string | undefined, name: string | undefined) {
  return useQuery({
    queryKey: keys.one(owner ?? '', name ?? ''),
    queryFn: async () => toModel(await api<WireModel>(base(owner!, name!))),
    enabled: !!owner && !!name,
    retry: false,
  })
}

export interface NewModel {
  name: string
  description: string
  tasks: string[]
  inputs: string[]
  license: string
  languages: string[]
  visibility: 'public' | 'private'
}

export function useCreateModel() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (input: NewModel): Promise<Model> => toModel(await api<WireModel>('/api/models', { method: 'POST', json: input })),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.lists }),
  })
}

/** Like or unlike: the count and the heart come back from the server, so they are never guessed. */
export function useLike(model: Model) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (like: boolean) =>
      api<{ liked: boolean; likes: number }>(`${base(model.owner, model.name)}/like`, { method: like ? 'PUT' : 'DELETE' }),
    onSuccess: (answer) => {
      client.setQueryData(keys.one(model.owner, model.name), (old: Model | undefined) => old && { ...old, ...answer })
      void client.invalidateQueries({ queryKey: keys.lists })
    },
  })
}

export function useDeleteModel(model: Model) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<void>(base(model.owner, model.name), { method: 'DELETE' }),
    onSuccess: () => {
      client.removeQueries({ queryKey: keys.one(model.owner, model.name) })
      return client.invalidateQueries({ queryKey: keys.lists })
    },
  })
}

// ---- who has access besides its creator (the people who can edit the model only)

export function useMembers(model: Model, enabled: boolean) {
  return useQuery({
    queryKey: keys.members(model.owner, model.name),
    queryFn: async (): Promise<Member[]> => (await api<WireMember[]>(`${base(model.owner, model.name)}/members`)).map(toMember),
    enabled,
  })
}

export function useSetMember(model: Model) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Member['role'] }) =>
      api<WireMember>(`${base(model.owner, model.name)}/members/${encodeURIComponent(userId)}`, { method: 'PUT', json: { role } }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.members(model.owner, model.name) }),
  })
}

export function useRemoveMember(model: Model) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => api<void>(`${base(model.owner, model.name)}/members/${encodeURIComponent(userId)}`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.members(model.owner, model.name) }),
  })
}
