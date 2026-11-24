import { seeded } from '../components/viewers/seed'

/** A generated sound: real samples, so it can be played and drawn until the backend serves the real files. */
export interface Clip { samples: Float32Array; rate: number; duration: number; peaks: number[] }

const cache = new Map<string, Clip>()
const RATE = 8000
const BINS = 600

/** Bursts of tone (like calls or syllables) over a little noise, always the same for the same file. */
export function clipFor(file: string, duration: number): Clip {
  const key = `${file}:${duration}`
  const hit = cache.get(key)
  if (hit) return hit
  const rnd = seeded(file)
  const n = Math.floor(duration * RATE)
  const samples = new Float32Array(n)
  const bursts = Array.from({ length: 5 + Math.floor(rnd() * 5) }, () => ({
    start: rnd() * Math.max(0.1, duration - 1.5), len: 0.3 + rnd() * 1.3, f0: 300 + rnd() * 1500, sweep: (rnd() - 0.5) * 900, am: 2 + rnd() * 6, gain: 0.2 + rnd() * 0.25,
  }))
  for (const b of bursts) {
    const from = Math.floor(b.start * RATE), to = Math.min(n, Math.floor((b.start + b.len) * RATE))
    for (let i = from; i < to; i++) {
      const t = (i - from) / RATE
      const env = Math.sin((Math.PI * t) / b.len) ** 2
      samples[i] += b.gain * env * Math.sin(2 * Math.PI * (b.f0 * t + 0.5 * b.sweep * t * t)) * (0.6 + 0.4 * Math.sin(2 * Math.PI * b.am * t))
    }
  }
  for (let i = 0; i < n; i++) samples[i] += 0.015 * (rnd() * 2 - 1)

  const per = Math.max(1, Math.floor(n / BINS))
  const peaks = Array.from({ length: BINS }, (_, b) => {
    let m = 0
    for (let i = b * per; i < Math.min(n, (b + 1) * per); i++) m = Math.max(m, Math.abs(samples[i]))
    return m
  })
  const top = Math.max(...peaks, 0.001)
  const clip = { samples, rate: RATE, duration, peaks: peaks.map((p) => p / top) }
  cache.set(key, clip)
  return clip
}

export const fmtTime = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`
