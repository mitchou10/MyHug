import { hue, seeded } from './seed'

/** A generated scene (sky, ground, a few shapes) drawn in the coordinates of the image. Stands in for the real file. */
export function SceneGraphics({ file, width, height }: { file: string; width: number; height: number }) {
  const rnd = seeded(file)
  const a = hue(file)
  const id = `sky-${file.replace(/\W/g, '')}`
  const horizon = height * (0.45 + rnd() * 0.15)
  const shapes = Array.from({ length: 7 }, (_, i) => ({
    x: rnd() * width * 0.85, w: width * (0.05 + rnd() * 0.12), h: height * (0.1 + rnd() * 0.3), fill: `hsl(${(a + i * 47) % 360} 45% ${35 + rnd() * 25}%)`, round: rnd() > 0.5,
  }))
  return (
    <g>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={`hsl(${a} 60% 72%)`} />
          <stop offset="1" stopColor={`hsl(${(a + 40) % 360} 60% 88%)`} />
        </linearGradient>
      </defs>
      <rect width={width} height={height} fill={`url(#${id})`} />
      <rect y={horizon} width={width} height={height - horizon} fill={`hsl(${(a + 200) % 360} 12% 38%)`} />
      {shapes.map((s, i) => s.round
        ? <ellipse key={i} cx={s.x + s.w / 2} cy={horizon - s.h / 2} rx={s.w / 2} ry={s.h / 2} fill={s.fill} />
        : <rect key={i} x={s.x} y={horizon - s.h} width={s.w} height={s.h} fill={s.fill} />)}
    </g>
  )
}
