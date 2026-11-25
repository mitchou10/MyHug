import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { base } from './keys'
import type { WirePredict } from './wire'

/** Tries a model: the input goes to the relay of the platform, which asks the server that serves it. */
export function usePredict(owner: string, name: string) {
  return useMutation({
    mutationFn: async (input: unknown) => {
      const answer = await api<WirePredict>(`${base(owner, name)}/predict`, { method: 'POST', json: { input } })
      return { output: answer.output, tookMs: answer.took_ms }
    },
  })
}
