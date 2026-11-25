import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { ModelFile, ModelVersion } from '../types'
import { base, keys } from './keys'
import { toFile, toVersion } from './mappers'
import type { WireVersion, WireVersionDetail } from './wire'

/** How often a version that a worker has not finished with is asked about again. */
export const WAITING_POLL_MS = 3_000

/** The newest first. While one is being checked, the list asks again: the badge turns by itself. */
export function useVersions(owner: string, name: string) {
  return useQuery({
    queryKey: keys.versions(owner, name),
    queryFn: async (): Promise<ModelVersion[]> => (await api<WireVersion[]>(`${base(owner, name)}/versions`)).map(toVersion),
    refetchInterval: (query) => {
      const versions = query.state.data
      const waiting = versions?.some((v) => v.status === 'pending' || v.status === 'processing' || v.code?.state === 'unresolved' || v.code?.state === 'resolving')
      return waiting ? WAITING_POLL_MS : false
    },
  })
}

/** One version and its files. */
export function useVersionFiles(owner: string, name: string, number: number | null) {
  return useQuery({
    queryKey: keys.version(owner, name, number ?? 0),
    queryFn: async (): Promise<{ version: ModelVersion; files: ModelFile[] }> => {
      const { files, ...version } = await api<WireVersionDetail>(`${base(owner, name)}/versions/${number}`)
      return { version: toVersion(version), files: files.map(toFile) }
    },
    enabled: number !== null && number > 0,
  })
}

export interface CodeInput {
  url: string
  ref?: string
  path?: string
  entrypoint?: string
}

/** A version that is only a link to the code. */
export function useCreateCodeVersion(owner: string, name: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (input: { code: CodeInput; message: string }) => toVersion(await api<WireVersion>(`${base(owner, name)}/versions`, { method: 'POST', json: input })),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.all }),
  })
}

export function useDeleteVersion(owner: string, name: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (number: number) => api<void>(`${base(owner, name)}/versions/${number}`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.all }),
  })
}

/** Where a file is downloaded from: the API answers with a redirection to a signed address of the storage. */
export const downloadAddress = (owner: string, name: string, path: string, version: number) =>
  `${base(owner, name)}/files/${path.split('/').map(encodeURIComponent).join('/')}?version=${version}`
