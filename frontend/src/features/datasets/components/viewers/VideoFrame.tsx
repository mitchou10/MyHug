import type { ReactNode } from 'react'
import { shapesAt, VIDEO_H, VIDEO_W } from '../../annotation/videoMock'
import { SceneGraphics } from './SceneGraphics'

/** One frame of a generated video at time `t`: a scene with a few shapes that move. `children` are drawn on top, in pixels. */
export function VideoFrame({ file, t, children }: { file: string; t: number; children?: ReactNode }) {
  return (
    <>
      <SceneGraphics file={file} width={VIDEO_W} height={VIDEO_H} />
      {shapesAt(file, t).map((s, i) => s.round
        ? <ellipse key={i} cx={s.x + s.w / 2} cy={s.y + s.h / 2} rx={s.w / 2} ry={s.h / 2} fill={`hsl(${s.hue} 60% 45%)`} />
        : <rect key={i} x={s.x} y={s.y} width={s.w} height={s.h} rx={8} fill={`hsl(${s.hue} 60% 45%)`} />)}
      {children}
    </>
  )
}
