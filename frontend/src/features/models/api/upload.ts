import { api, ApiError } from '@/lib/api'
import { base } from './keys'
import type { CodeInput } from './versions'
import type { WireUpload, WireUploadFile, WireVersion } from './wire'

/** How many parts go at the same time, and how often a part is tried. */
export const PARALLEL_PARTS = 3
const ATTEMPTS = 3

export class UploadCancelled extends Error {
  constructor() {
    super('The upload was cancelled')
  }
}

/** A part that the storage refused, or that did not arrive. */
export class PartFailed extends Error {
  readonly path: string
  readonly number: number

  constructor(path: string, number: number) {
    super(`The part ${number} of ${path} did not reach the storage`)
    this.path = path
    this.number = number
  }
}

/** The file the browser holds is not the one that was announced (another size): nothing is sent. */
export class WrongFile extends Error {
  readonly path: string

  constructor(path: string) {
    super(`${path} is not the file that was announced`)
    this.path = path
  }
}

export interface Progress {
  sent: number
  total: number
}

export interface Announcement {
  files: { file: File; path: string }[]
  message: string
  remove: string[]
  code?: CodeInput
}

/** Tells the API which files are coming (nothing is sent yet). It answers how each one is cut. */
export function announce(owner: string, name: string, input: Announcement) {
  return api<WireUpload>(`${base(owner, name)}/uploads`, {
    method: 'POST',
    json: {
      files: input.files.map(({ file, path }) => ({ path, size: file.size, content_type: file.type || null })),
      remove: input.remove,
      message: input.message,
      code: input.code ?? null,
    },
  })
}

/** An upload, and the parts that reached the storage: what is needed to go on after a reload. */
export const status = (id: string) => api<WireUpload>(`/api/model-uploads/${id}?parts=true`)

export const abort = (id: string) => api<void>(`/api/model-uploads/${id}`, { method: 'DELETE' })

export const complete = (id: string) => api<WireVersion>(`/api/model-uploads/${id}/complete`, { method: 'POST' })

interface Options {
  signal?: AbortSignal
  onProgress?: (progress: Progress) => void
}

const sign = (id: string, fileId: string, numbers: number[]) =>
  api<{ parts: { number: number; url: string }[] }>(`/api/model-uploads/${id}/parts`, { method: 'POST', json: { file_id: fileId, numbers } })

function partOf(file: File, entry: WireUploadFile, number: number) {
  const start = (number - 1) * entry.part_size
  return file.slice(start, Math.min(start + entry.part_size, file.size))
}

/** Sends a part to its signed address, again if it fails (with a fresh address: the first may have expired). */
async function sendPart(id: string, entry: WireUploadFile, file: File, number: number, signal?: AbortSignal) {
  for (let attempt = 1; attempt <= ATTEMPTS; attempt++) {
    if (signal?.aborted) throw new UploadCancelled()
    try {
      const { parts } = await sign(id, entry.id, [number])
      const response = await fetch(parts[0].url, { method: 'PUT', body: partOf(file, entry, number), signal })
      if (response.ok) return
    } catch (error) {
      if (signal?.aborted) throw new UploadCancelled()
      if (error instanceof ApiError) throw error // the API says no (expired, given up): trying again will not change it
    }
  }
  throw new PartFailed(entry.path, number)
}

/**
 * Sends the parts that are not in the storage yet, a few at a time, straight to the signed addresses (the files never
 * go through the API). What was received before (a reload, a lost connection) is asked of the API, and not sent again.
 * It does not complete the upload: the caller does, once nothing is missing.
 */
export async function sendParts(id: string, files: Map<string, File>, { signal, onProgress }: Options = {}) {
  const upload = await status(id)
  if (upload.status !== 'open') throw new ApiError(409, `The upload is ${upload.status}`)

  const entries = upload.files.filter((entry) => !entry.already_stored)
  const total = entries.reduce((sum, entry) => sum + entry.size_bytes, 0)
  let sent = 0
  const todo: { entry: WireUploadFile; file: File; number: number }[] = []
  for (const entry of entries) {
    const file = files.get(entry.path)
    if (!file || file.size !== entry.size_bytes) throw new WrongFile(entry.path)
    const received = new Map((entry.received ?? []).map((part) => [part.number, part.size]))
    for (let number = 1; number <= entry.parts_count; number++) {
      const size = partOf(file, entry, number).size
      if (received.get(number) === size) sent += size
      else todo.push({ entry, file, number })
    }
  }
  onProgress?.({ sent, total })

  // Each part has its own signed address, asked for just before it is sent: they expire.
  let next = 0
  const worker = async () => {
    while (next < todo.length) {
      if (signal?.aborted) throw new UploadCancelled()
      const { entry, file, number } = todo[next++]
      await sendPart(id, entry, file, number, signal)
      sent += partOf(file, entry, number).size
      onProgress?.({ sent, total })
    }
  }
  await Promise.all(Array.from({ length: Math.min(PARALLEL_PARTS, todo.length) }, worker))
}
