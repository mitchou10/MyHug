import { seeded } from '../components/viewers/seed'

/** A generated series (weekly sales) with a trend, a seasonal pattern, a promotion, a stock-out and a shift in level. */
export function seriesFor(id: string, n: number): number[] {
  const rnd = seeded(id)
  const base = 50 + rnd() * 50, trend = (rnd() - 0.5) * 0.4, amp = 8 + rnd() * 8
  const promo = 15 + Math.floor(rnd() * 25), stockout = 50 + Math.floor(rnd() * 15), shift = 70 + Math.floor(rnd() * 20)
  return Array.from({ length: n }, (_, i) => {
    let v = base + trend * i + amp * Math.sin((2 * Math.PI * i) / 13) + (rnd() - 0.5) * 8
    if (i >= promo && i < promo + 3) v += 35
    if (i >= stockout && i < stockout + 2) v *= 0.1
    if (i >= shift) v += 18
    return Math.max(0, v)
  })
}

/** The date of the `i`-th point of a weekly series. */
export const dateAt = (start: string, i: number) => new Date(Date.parse(start) + Math.round(i) * 7 * 86_400_000).toISOString().slice(0, 10)
