import { afterEach, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api'
import { createFakeModelsApi } from '@/test/fakeModelsApi'
import { Reply } from '@/test/fakeFeedbackApi'
import { announce, PartFailed, sendParts, UploadCancelled, WrongFile } from './upload'

const user = { user_id: 'u1', username: 'bob', name: 'Bob', is_admin: false }

/** The engine against the API in memory: `fetch` is the fake, so what is asked of the API and of the storage is read. */
function setup(partSize = 4) {
  const fake = createFakeModelsApi(user, [{ owner: 'bob', name: 'm' }], { partSize })
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${(init?.method ?? 'GET')} ${url}`)
    const answer = fake.handle(url, init) ?? new Reply(404, { detail: 'nope' })
    return { ok: answer.status < 400, status: answer.status, statusText: String(answer.status), json: async () => answer.body }
  }))
  return { fake, calls }
}

const file = (size: number) => new File([new Uint8Array(size)], 'w.bin')
const send = (size: number) => announce('bob', 'm', { files: [{ file: file(size), path: 'w.bin' }], message: '', remove: [] })

afterEach(() => vi.unstubAllGlobals())

it('sends every part to its own signed address and reports the bytes that went', async () => {
  const { fake } = setup()
  const upload = await send(10)
  expect(upload.files[0]).toMatchObject({ parts_count: 3, part_size: 4 })
  const progress: number[] = []
  await sendParts(upload.id, new Map([['w.bin', file(10)]]), { onProgress: (p) => progress.push(p.sent) })
  expect([...fake.sentParts].sort()).toEqual([1, 2, 3].map((n) => `https://storage.test/${upload.id}/${upload.files[0].id}/${n}`))
  expect(progress[0]).toBe(0)
  expect(progress.at(-1)).toBe(10)
  expect(progress).toEqual([...progress].sort((a, b) => a - b)) // it only goes forward
})

it('does not send again what the storage already holds, which is what resuming is', async () => {
  const { fake } = setup()
  const upload = await send(10)
  const id = upload.files[0].id
  fake.handle(`https://storage.test/${upload.id}/${id}/1`, { method: 'PUT', body: new Blob(['abcd']) })
  fake.handle(`https://storage.test/${upload.id}/${id}/3`, { method: 'PUT', body: new Blob(['ab']) })
  fake.sentParts.length = 0
  const progress: number[] = []
  await sendParts(upload.id, new Map([['w.bin', file(10)]]), { onProgress: (p) => progress.push(p.sent) })
  expect(fake.sentParts).toEqual([`https://storage.test/${upload.id}/${id}/2`])
  expect(progress[0]).toBe(6) // the progress starts from what is there
  expect(progress.at(-1)).toBe(10)
})

it('sends again a part that arrived with the wrong size', async () => {
  const { fake } = setup()
  const upload = await send(10)
  const id = upload.files[0].id
  fake.handle(`https://storage.test/${upload.id}/${id}/1`, { method: 'PUT', body: new Blob(['ab']) }) // cut short
  fake.sentParts.length = 0
  await sendParts(upload.id, new Map([['w.bin', file(10)]]))
  expect(fake.sentParts).toContain(`https://storage.test/${upload.id}/${id}/1`)
})

it('tries a refused part again, with a fresh address, and goes on', async () => {
  const { fake, calls } = setup(10)
  const upload = await send(10)
  fake.refuseParts(2)
  await sendParts(upload.id, new Map([['w.bin', file(10)]]))
  expect(fake.sentParts).toHaveLength(3) // refused twice, accepted the third time
  expect(calls.filter((c) => c.startsWith('POST') && c.endsWith('/parts'))).toHaveLength(3) // an address each time
})

it('gives up on a part that the storage keeps refusing, and says which', async () => {
  const { fake } = setup(10)
  const upload = await send(10)
  fake.refuseParts(10)
  const error = await sendParts(upload.id, new Map([['w.bin', file(10)]])).catch((e: unknown) => e)
  expect(error).toBeInstanceOf(PartFailed)
  expect(error).toMatchObject({ path: 'w.bin', number: 1 })
})

it('does not send a file that is not the one that was announced', async () => {
  const { fake } = setup()
  const upload = await send(10)
  await expect(sendParts(upload.id, new Map([['w.bin', file(11)]]))).rejects.toBeInstanceOf(WrongFile)
  await expect(sendParts(upload.id, new Map())).rejects.toBeInstanceOf(WrongFile)
  expect(fake.sentParts).toHaveLength(0)
})

it('stops at once when it is cancelled', async () => {
  const { fake } = setup()
  const upload = await send(10)
  const stop = new AbortController()
  stop.abort()
  await expect(sendParts(upload.id, new Map([['w.bin', file(10)]]), { signal: stop.signal })).rejects.toBeInstanceOf(UploadCancelled)
  expect(fake.sentParts).toHaveLength(0)
})

it('refuses to send into an upload that was given up', async () => {
  const { fake } = setup()
  const upload = await send(10)
  fake.uploads[0].upload.status = 'expired'
  await expect(sendParts(upload.id, new Map([['w.bin', file(10)]]))).rejects.toBeInstanceOf(ApiError)
})
