import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '@/lib/api'
import { keys } from './keys'
import { abort, announce, complete, sendParts, status, UploadCancelled, type Announcement, type Progress } from './upload'
import type { WireUpload } from './wire'

export type Phase =
  | { kind: 'idle' }
  | { kind: 'sending'; progress: Progress }
  | { kind: 'completing' }
  | { kind: 'done'; version: number }
  | { kind: 'failed'; error: unknown }

const slot = (owner: string, name: string) => `myhug.model-upload.${owner}/${name}`
const remembered = (owner: string, name: string) => localStorage.getItem(slot(owner, name))

/** The files of a file list, by the path they will have in the version. */
export const byPath = (files: { file: File; path: string }[]) => new Map(files.map(({ file, path }) => [path, file]))

/**
 * Announce, send and complete the upload of a version. The id of the upload is kept in the browser while it is open:
 * after a reload `pending` is what is left of it, and `resume` goes on with the same files from the parts that
 * reached the storage. Nothing but the id is kept: the files themselves are chosen again.
 */
export function useUpload(owner: string, name: string) {
  const client = useQueryClient()
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  const [pending, setPending] = useState<WireUpload | null>(null)
  const controller = useRef<AbortController | null>(null)
  const current = useRef<string | null>(null)

  const forget = useCallback(() => {
    localStorage.removeItem(slot(owner, name))
    current.current = null
    setPending(null)
  }, [owner, name])

  // An upload that was interrupted (a reload, a closed tab): is it still open, and what has reached the storage?
  useEffect(() => {
    const id = remembered(owner, name)
    if (!id) return
    let cancelled = false
    status(id)
      .then((upload) => {
        if (cancelled) return
        if (upload.status === 'open') {
          current.current = id
          setPending(upload)
        } else forget()
      })
      .catch((error) => {
        if (!cancelled && error instanceof ApiError) forget() // gone, or not mine any more
      })
    return () => {
      cancelled = true
    }
  }, [owner, name, forget])

  const run = useCallback(
    async (id: string, files: Map<string, File>) => {
      const stop = new AbortController()
      controller.current = stop
      setPhase({ kind: 'sending', progress: { sent: 0, total: 0 } })
      try {
        await sendParts(id, files, { signal: stop.signal, onProgress: (progress) => setPhase({ kind: 'sending', progress }) })
        setPhase({ kind: 'completing' })
        const version = await complete(id)
        forget()
        await client.invalidateQueries({ queryKey: keys.all })
        setPhase({ kind: 'done', version: version.number })
      } catch (error) {
        // A cancel is the person's: the upload is already given up. Any other failure keeps it, to be resumed.
        setPhase(error instanceof UploadCancelled ? { kind: 'idle' } : { kind: 'failed', error })
        if (error instanceof ApiError && error.status === 404) forget()
        // What reached the storage is kept: the person can choose the files again and go on.
        else if (!(error instanceof UploadCancelled)) void status(id).then(setPending, () => undefined)
      } finally {
        controller.current = null
      }
    },
    [client, forget],
  )

  const start = useCallback(
    async (input: Announcement) => {
      try {
        const upload = await announce(owner, name, input)
        localStorage.setItem(slot(owner, name), upload.id)
        current.current = upload.id
        await run(upload.id, byPath(input.files))
      } catch (error) {
        setPhase({ kind: 'failed', error })
      }
    },
    [owner, name, run],
  )

  const resume = useCallback(
    (files: { file: File; path: string }[]) => (current.current ? run(current.current, byPath(files)) : Promise.resolve()),
    [run],
  )

  /** Stops sending and gives the upload up: what reached the storage is thrown away. */
  const cancel = useCallback(async () => {
    controller.current?.abort()
    const id = current.current
    forget()
    setPhase({ kind: 'idle' })
    if (id) await abort(id).catch(() => undefined)
  }, [forget])

  const reset = useCallback(() => setPhase({ kind: 'idle' }), [])

  return { phase, pending, start, resume, cancel, reset }
}
