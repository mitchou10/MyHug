import { seeded } from '../components/viewers/seed'

export const VIDEO_W = 1280
export const VIDEO_H = 720

export interface MovingShape { x: number; y: number; w: number; h: number; hue: number; round: boolean }

/** The moving shapes of a generated "video" at time `t` (pixels): always the same for the same file. */
export function shapesAt(file: string, t: number): MovingShape[] {
  const rnd = seeded(file)
  return Array.from({ length: 3 }, (_, i) => {
    const w = VIDEO_W * (0.12 + rnd() * 0.1), h = VIDEO_H * (0.16 + rnd() * 0.14)
    const cx = VIDEO_W * (0.3 + rnd() * 0.4), cy = VIDEO_H * (0.35 + rnd() * 0.3)
    const ax = VIDEO_W * (0.1 + rnd() * 0.15), ay = VIDEO_H * (0.05 + rnd() * 0.1)
    const period = 4 + rnd() * 5, phase = rnd() * Math.PI * 2
    return {
      x: cx + ax * Math.sin((2 * Math.PI * t) / period + phase) - w / 2,
      y: cy + ay * Math.cos((2 * Math.PI * t) / (period * 0.7) + phase) - h / 2,
      w, h, hue: (rnd() * 360 + i * 70) % 360, round: i === 1,
    }
  })
}
