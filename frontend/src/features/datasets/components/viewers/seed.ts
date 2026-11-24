/** Deterministic pseudo-random numbers from a string, so mock visuals stay stable between renders. */
export function seeded(key: string) {
  let h = 2166136261
  for (const c of key) h = Math.imul(h ^ c.charCodeAt(0), 16777619)
  return () => ((h = Math.imul(h ^ (h >>> 15), 2246822507) + 0x6d2b79f5), ((h ^ (h >>> 13)) >>> 0) / 4294967296)
}
export const hue = (key: string) => Math.floor(seeded(key)() * 360)
