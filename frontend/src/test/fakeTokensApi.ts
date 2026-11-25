/** The access tokens API in memory, with the rules of the real one: mine only, the secret given once and never kept. */
import type { WireCreatedToken, WireToken } from '@/features/tokens/api/wire'
import { Reply, type FakeUser } from './fakeFeedbackApi'

export interface FakeTokensApi {
  handle: (url: string, init?: RequestInit) => Reply | undefined
  /** What the server holds: no secret among it, only what identifies each token. */
  tokens: (WireToken & { owner: string })[]
  /** Makes the next creation fail with this answer. */
  refuseNext: Reply | null
}

let counter = 0

export function createFakeTokensApi(user: FakeUser | null): FakeTokensApi {
  const tokens: FakeTokensApi['tokens'] = []
  const api: FakeTokensApi = { handle, tokens, refuseNext: null }

  function handle(url: string, init: RequestInit = {}): Reply | undefined {
    if (!url.startsWith('/api/tokens')) return undefined
    if (!user) return new Reply(401, { detail: 'Not authenticated' })
    const method = (init.method ?? 'GET').toUpperCase()
    const mine = () => tokens.filter((t) => t.owner === user.user_id)
    const view = ({ owner: _owner, ...token }: FakeTokensApi['tokens'][number]): WireToken => (void _owner, token)

    if (url === '/api/tokens' && method === 'GET') return new Reply(200, [...mine()].reverse().map(view))
    if (url === '/api/tokens' && method === 'POST') {
      if (api.refuseNext) {
        const answer = api.refuseNext
        api.refuseNext = null
        return answer
      }
      const body = JSON.parse(String(init.body)) as { name: string; scope: string; expires_in_days: number | null }
      if (!body.name.trim() || !['read', 'write'].includes(body.scope)) return new Reply(422, { detail: 'Not valid' })
      const id = `token-${++counter}`
      const secret = `mh_secret${String(counter).padStart(35, '0')}`
      const token = {
        id, name: body.name.trim(), scope: body.scope as 'read' | 'write', prefix: secret.slice(0, 11), created_at: '2026-11-01T09:00:00Z',
        expires_at: body.expires_in_days ? new Date(Date.parse('2026-11-01T09:00:00Z') + body.expires_in_days * 86_400_000).toISOString() : null,
        last_used_at: null, revoked_at: null, owner: user.user_id,
      }
      tokens.push(token)
      const created: WireCreatedToken = { ...view(token), token: secret }
      return new Reply(201, created)
    }
    const one = url.match(/^\/api\/tokens\/([^/]+)$/)
    if (one && method === 'DELETE') {
      const found = mine().find((t) => t.id === one[1])
      if (!found) return new Reply(404, { detail: 'This token does not exist' })
      found.revoked_at ??= '2026-11-02T09:00:00Z'
      return new Reply(204)
    }
    return undefined
  }
  return api
}
