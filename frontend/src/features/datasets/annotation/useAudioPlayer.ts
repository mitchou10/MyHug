import { useCallback, useEffect, useRef, useState } from 'react'
import type { Clip } from './audioMock'

/** Plays a clip with the Web Audio API: play from a time, up to a time, at a speed, and follow the position. */
export function useAudioPlayer(clip: Clip) {
  const ctx = useRef<AudioContext | null>(null)
  const src = useRef<AudioBufferSourceNode | null>(null)
  const run = useRef({ at: 0, from: 0, to: clip.duration, speed: 1 })
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [speed, setSpeedState] = useState(1)

  const stop = useCallback(() => {
    const s = src.current
    if (s) { s.onended = null; try { s.stop() } catch { /* already stopped */ } }
    src.current = null
    setPlaying(false)
  }, [])

  const play = useCallback((from: number, to: number = clip.duration, rate = run.current.speed) => {
    stop()
    const c = (ctx.current ??= new AudioContext())
    void c.resume()
    const buffer = c.createBuffer(1, clip.samples.length, clip.rate)
    buffer.copyToChannel(new Float32Array(clip.samples), 0)
    const s = c.createBufferSource()
    s.buffer = buffer
    s.playbackRate.value = rate
    s.connect(c.destination)
    const start = Math.min(Math.max(0, from), clip.duration - 0.01)
    s.start(0, start, Math.max(0.01, to - start))
    run.current = { at: c.currentTime, from: start, to, speed: rate }
    s.onended = () => { if (src.current === s) { src.current = null; setPlaying(false); setTime(to) } }
    src.current = s
    setPlaying(true)
  }, [clip, stop])

  // Follow the position while playing.
  useEffect(() => {
    if (!playing) return
    let raf = 0
    const tick = () => {
      const r = run.current
      setTime(Math.min(r.to, r.from + (ctx.current!.currentTime - r.at) * r.speed))
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing])

  // A new clip: stop and go back to the start. Leaving the page: release the audio device.
  useEffect(() => { stop(); setTime(0) }, [clip, stop])
  useEffect(() => () => { stop(); void ctx.current?.close(); ctx.current = null }, [stop])

  return {
    playing, time, speed,
    toggle: () => (playing ? stop() : play(time >= clip.duration - 0.05 ? 0 : time)),
    playRange: (from: number, to: number) => { setTime(from); play(from, to) },
    seek: (t: number) => { const x = Math.min(Math.max(0, t), clip.duration); setTime(x); if (playing) play(x) },
    setSpeed: (r: number) => { setSpeedState(r); run.current.speed = r; if (playing) play(time, run.current.to, r) },
    pause: stop,
  }
}
