/**
 * The models API in memory, with the rules of the real one: what a person sees (a private model that is not theirs is a
 * 404), the filters and the pages of the list, the likes, the versions, the access, the relay that tries a model, and
 * the upload in parts (announce, sign, send to the storage, complete, resume, give up). The screens are tested against
 * it, the real backend against its own tests.
 */
import type { WireFile, WireMember, WireModel, WirePage, WireUpload, WireVersion } from '@/features/models/api/wire'
import { Reply, type FakeUser } from './fakeFeedbackApi'

const T = '2026-11-01T09:00:00Z'
const fail = (status: number, detail: string) => new Reply(status, { detail })

export type SeedModel = Partial<WireModel> & Pick<WireModel, 'owner' | 'name'>

interface Stored {
  model: WireModel
  versions: (WireVersion & { files: WireFile[] })[]
  members: WireMember[]
}

interface StoredUpload {
  upload: WireUpload
  model: Stored
  received: Map<string, Map<number, number>>
  message: string
  code: WireVersion['code']
}

export interface FakeModelsApi {
  handle: (url: string, init?: RequestInit) => Reply | undefined
  models: Stored[]
  uploads: StoredUpload[]
  /** The next `count` parts sent to the storage are refused. */
  refuseParts: (count: number) => void
  /** How the relay answers (default: two labels for a text). */
  predict: (input: unknown) => Reply | unknown
  /** The addresses the browser sent parts to, in order. */
  sentParts: string[]
  /** What the API answers when an upload is announced, instead of accepting it. */
  announcement: Reply | null
}

let counter = 0

const build = (seed: SeedModel): WireModel => ({
  id: `model-${++counter}`, description: '', tasks: ['classification'], inputs: ['text'], library: '', languages: [], license: 'mit',
  tags: [], visibility: 'public', code_url: null, parameters: null, trained_on: [], downloads: 0, likes: 0, liked: false, version: 0,
  size_bytes: 0, created_by: 'u-0', created_by_username: seed.owner, created_at: T, updated_at: T, card: '', can_edit: false, serving: null,
  ...seed,
})

export function createFakeModelsApi(user: FakeUser | null, seed: SeedModel[] = [], options: { partSize?: number } = {}): FakeModelsApi {
  const models: Stored[] = seed.map((s) => ({ model: build(s), versions: [], members: [] }))
  const uploads: StoredUpload[] = []
  const sentParts: string[] = []
  let refused = 0
  const partSize = options.partSize ?? 4
  const api: FakeModelsApi = {
    handle, models, uploads, sentParts, announcement: null,
    refuseParts: (count) => { refused = count },
    predict: () => [{ label: 'positive', score: 0.8 }, { label: 'negative', score: 0.2 }],
  }

  const canSee = (s: Stored) => s.model.visibility === 'public' || (!!user && (s.model.owner === user.username || user.is_admin || s.members.some((m) => m.user_id === user.user_id)))
  const canEdit = (s: Stored) => !!user && (s.model.owner === user.username || user.is_admin || s.members.some((m) => m.user_id === user.user_id && m.role === 'maintainer'))
  const find = (owner: string, name: string) => models.find((s) => s.model.owner === owner && s.model.name === name)
  const view = (s: Stored): WireModel => {
    const { mlflow_url: _drop, ...rest } = s.model
    void _drop
    return { ...rest, can_edit: canEdit(s), ...(canEdit(s) && s.model.mlflow_url ? { mlflow_url: s.model.mlflow_url } : {}) }
  }
  const latest = (s: Stored) => s.versions[s.versions.length - 1]
  const refresh = (s: Stored) => {
    s.model.version = latest(s)?.number ?? 0
    s.model.size_bytes = latest(s)?.size_bytes ?? 0
  }
  const withoutFiles = ({ files: _files, ...v }: WireVersion & { files: WireFile[] }): WireVersion => (void _files, v)

  function handle(url: string, init: RequestInit = {}): Reply | undefined {
    const method = (init.method ?? 'GET').toUpperCase()
    const [path, query = ''] = url.split('?')
    const params = new URLSearchParams(query)
    const body = () => JSON.parse(String(init.body)) as Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any

    // The storage: a part is sent there with PUT, to the address the API signed.
    if (path.startsWith('https://storage.test/')) {
      sentParts.push(path)
      if (refused > 0) { refused--; return new Reply(403) }
      const [uploadId, fileId, number] = path.replace('https://storage.test/', '').split('/')
      const stored = uploads.find((u) => u.upload.id === uploadId)
      if (!stored) return new Reply(404)
      const parts = stored.received.get(fileId) ?? new Map<number, number>()
      parts.set(Number(number), (init.body as Blob).size)
      stored.received.set(fileId, parts)
      return new Reply(200)
    }
    if (!path.startsWith('/api/models') && !path.startsWith('/api/model-uploads')) return undefined
    if (!user && method !== 'GET') return fail(401, 'Not authenticated')

    const upload = path.match(/^\/api\/model-uploads\/([^/]+)(\/parts|\/complete)?$/)
    if (upload) {
      const stored = uploads.find((u) => u.upload.id === upload[1])
      if (!stored || !user || stored.upload.status === 'aborted') return fail(404, 'This upload does not exist')
      if (method === 'DELETE') { stored.upload.status = 'aborted'; return new Reply(204) }
      if (upload[2] === '/parts') {
        const { file_id, numbers } = body()
        return new Reply(200, { parts: (numbers as number[]).map((n) => ({ number: n, url: `https://storage.test/${stored.upload.id}/${file_id}/${n}` })), expires_in: 600 })
      }
      if (upload[2] === '/complete') {
        for (const f of stored.upload.files) {
          if (f.already_stored) continue
          const got = stored.received.get(f.id)
          if (!got || got.size !== f.parts_count) return fail(409, 'Some parts are missing')
        }
        const number = (latest(stored.model)?.number ?? 0) + 1
        const size = stored.upload.files.reduce((sum, f) => sum + f.size_bytes, 0)
        const version = {
          number, status: 'pending', error: null, size_bytes: size, message: stored.message, servable: false, code: stored.code,
          created_by: user.user_id, created_by_username: user.username, created_at: T,
          files: stored.upload.files.map((f) => ({ path: f.path, size_bytes: f.size_bytes, sha256: null, content_type: 'application/octet-stream' })),
        }
        stored.model.versions.push(version)
        refresh(stored.model)
        stored.upload.status = 'completed'
        return new Reply(200, withoutFiles(version))
      }
      const withParts = params.get('parts') === 'true'
      return new Reply(200, {
        ...stored.upload,
        files: stored.upload.files.map((f) => ({ ...f, received: withParts ? [...(stored.received.get(f.id) ?? [])].map(([number, size]) => ({ number, size })) : null })),
      })
    }

    if (path === '/api/models' && method === 'GET') {
      const limit = Number(params.get('limit') ?? 12)
      const offset = Number(params.get('offset') ?? 0)
      const q = (params.get('q') ?? '').toLowerCase()
      const sort = params.get('sort') ?? 'downloads'
      const found = models
        .filter(canSee)
        .map((s) => view(s))
        .filter((m) => (!q || `${m.owner}/${m.name} ${m.description} ${m.tags.join(' ')}`.toLowerCase().includes(q)) && (!params.get('modality') || m.inputs.includes(params.get('modality')!)) && (!params.get('task') || m.tasks.includes(params.get('task')!)))
        .sort((a, b) => (sort === 'likes' ? b.likes - a.likes : sort === 'updated' ? b.updated_at.localeCompare(a.updated_at) : b.downloads - a.downloads))
      const page: WirePage<WireModel> = { items: found.slice(offset, offset + limit), total: found.length, limit, offset }
      return new Reply(200, page)
    }
    if (path === '/api/models' && method === 'POST') {
      const data = body()
      if (find(user!.username, data.name)) return fail(409, 'A model with this name already exists')
      const stored: Stored = { model: build({ ...data, owner: user!.username, name: data.name } as SeedModel), versions: [], members: [] }
      models.push(stored)
      return new Reply(201, view(stored))
    }

    const one = path.match(/^\/api\/models\/([^/]+)\/([^/]+)(\/.*)?$/)
    if (!one) return undefined
    const stored = find(decodeURIComponent(one[1]), decodeURIComponent(one[2]))
    // A model that is private and not yours does not exist, as far as you can tell.
    if (!stored || !canSee(stored)) return fail(404, 'This model does not exist')
    const rest = one[3] ?? ''

    if (rest === '') {
      if (method === 'DELETE') {
        if (!canEdit(stored)) return fail(403, 'You cannot change this model')
        models.splice(models.indexOf(stored), 1)
        return new Reply(204)
      }
      return new Reply(200, view(stored))
    }
    if (rest === '/like') {
      if (!user) return fail(401, 'Not authenticated')
      stored.model.liked = method === 'PUT'
      stored.model.likes += method === 'PUT' ? 1 : -1
      return new Reply(200, { liked: stored.model.liked, likes: stored.model.likes })
    }
    if (rest === '/versions' && method === 'GET') return new Reply(200, [...stored.versions].reverse().map(withoutFiles))
    if (rest === '/versions' && method === 'POST') {
      if (!canEdit(stored)) return fail(403, 'You cannot change this model')
      const { code, message } = body()
      const number = (latest(stored)?.number ?? 0) + 1
      const version = {
        number, status: 'ready', error: null, size_bytes: 0, message, servable: false, created_by: user!.user_id, created_by_username: user!.username, created_at: T, files: [],
        code: { url: code.url, ref: code.ref ?? null, ref_kind: 'unknown', path: code.path ?? null, entrypoint: code.entrypoint ?? null, sha: null, state: 'unresolved', error: null, tree_url: null },
      }
      stored.versions.push(version)
      refresh(stored)
      return new Reply(201, withoutFiles(version))
    }
    const numbered = rest.match(/^\/versions\/(\d+)$/)
    if (numbered) {
      const version = stored.versions.find((v) => v.number === Number(numbered[1]))
      if (!version) return fail(404, 'This version does not exist')
      if (method === 'DELETE') {
        if (!canEdit(stored)) return fail(403, 'You cannot change this model')
        stored.versions.splice(stored.versions.indexOf(version), 1)
        refresh(stored)
        return new Reply(204)
      }
      return new Reply(200, version)
    }
    if (rest === '/uploads' && method === 'POST') {
      if (!canEdit(stored)) return fail(403, 'You cannot change this model')
      if (api.announcement) return api.announcement
      const data = body()
      const id = `upload-${++counter}`
      const created: WireUpload = {
        id, status: 'open', expires_at: '2026-11-02T09:00:00Z', version: null,
        files: (data.files as { path: string; size: number }[]).map((f, i) => ({ id: `${id}-f${i}`, path: f.path, size_bytes: f.size, part_size: partSize, parts_count: Math.ceil(f.size / partSize), already_stored: false, received: null })),
      }
      const entry: StoredUpload = { upload: created, model: stored, received: new Map(), message: data.message, code: data.code && { url: data.code.url, ref: data.code.ref ?? null, ref_kind: 'unknown', path: data.code.path ?? null, entrypoint: data.code.entrypoint ?? null, sha: null, state: 'unresolved', error: null, tree_url: null } }
      uploads.push(entry)
      return new Reply(201, created)
    }
    if (rest === '/members') {
      if (!canEdit(stored)) return fail(403, 'You cannot see who has access')
      return new Reply(200, stored.members)
    }
    const member = rest.match(/^\/members\/([^/]+)$/)
    if (member) {
      if (!canEdit(stored)) return fail(403, 'You cannot change who has access')
      const id = decodeURIComponent(member[1])
      stored.members = stored.members.filter((m) => m.user_id !== id)
      if (method === 'PUT') {
        const added = { user_id: id, role: body().role, added_by: user!.user_id, created_at: T }
        stored.members.push(added)
        return new Reply(200, added)
      }
      return new Reply(204)
    }
    if (rest === '/predict' && method === 'POST') {
      if (!stored.model.serving) return fail(409, 'This model is not served')
      const answer = api.predict(body().input)
      return answer instanceof Reply ? answer : new Reply(200, { output: answer, took_ms: 12 })
    }
    return undefined
  }
  return api
}
