import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { AccessToken, CreatedToken, NewToken, Scope } from '../types'
import type { WireCreatedToken, WireToken } from './wire'

const keys = { all: ['access-tokens'] as const }

const toToken = (token: WireToken): AccessToken => ({
  id: token.id,
  name: token.name,
  scope: token.scope as Scope,
  prefix: token.prefix,
  createdAt: token.created_at,
  expiresAt: token.expires_at,
  lastUsedAt: token.last_used_at,
  revokedAt: token.revoked_at,
})

/** My tokens, the newest first. Never the tokens themselves: the API does not have them any more. */
export function useTokens() {
  return useQuery({
    queryKey: keys.all,
    queryFn: async () => (await api<WireToken[]>('/api/tokens')).map(toToken),
  })
}

/** Makes a token. Its secret is only in the answer: it is kept by the caller as long as it shows it, never cached. */
export function useCreateToken() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (input: NewToken): Promise<CreatedToken> => {
      const { token, ...rest } = await api<WireCreatedToken>('/api/tokens', {
        method: 'POST',
        json: { name: input.name, scope: input.scope, expires_in_days: input.expiresInDays },
      })
      return { ...toToken(rest), secret: token }
    },
    onSuccess: () => client.invalidateQueries({ queryKey: keys.all }),
    gcTime: 0, // the answer holds the secret: nothing keeps it once the dialog lets go
  })
}

export function useRevokeToken() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/api/tokens/${id}`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.all }),
  })
}
