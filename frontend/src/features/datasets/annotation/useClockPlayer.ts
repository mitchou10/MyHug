import { useCallback, useEffect, useRef, useState } from 'react'
import type { Player } from './useAudioPlayer'

/** Plays a "video" that has no file behind it: a clock that advances at the chosen speed, with the same API as the audio player. */
export function useClockPlayer(duration: number, fps = 25): Player & { step: (frames: number) => void } {
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [speed, setSpeedState] = useState(1)
  const run = useRef({ at: 0, from: 0, to: duration, speed: 1 })

  const pause = useCallback(() => setPlaying(false), [])
  const play = useCallback((from: number, to: number = duration, rate = run.current.speed) => {
    run.current = { at: performance.now(), from, to, speed: rate }
    setTime(from)
    setPlaying(true)
  }, [duration])

  useEffect(() => {
    if (!playing) return
    let raf = 0
    const tick = () => {
      const r = run.current
      const t = r.from + ((performance.now() - r.at) / 1000) * r.speed
      if (t >= r.to) { setTime(r.to); setPlaying(false); return }
      setTime(t)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing])

  useEffect(() => { setPlaying(false); setTime(0) }, [duration])

  const clamp = (t: number) => Math.min(Math.max(0, t), duration)
  return {
    playing, time, speed, pause,
    toggle: () => (playing ? pause() : play(time >= duration - 0.05 ? 0 : time)),
    playRange: (from, to) => play(from, to),
    seek: (t) => { const x = clamp(t); setTime(x); if (playing) play(x, run.current.to) },
    setSpeed: (r) => { setSpeedState(r); run.current = { ...run.current, from: time, at: performance.now(), speed: r } },
    step: (frames) => { pause(); setTime((cur) => clamp(Math.round(cur * fps + frames) / fps)) },
  }
}
