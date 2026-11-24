import { hue } from '../components/viewers/seed'

/** The colors of a label (or of anything with a stable id): a soft background, a border and a readable text. */
export const color = (id: string) => ({ background: `hsl(${hue(id)} 80% 88%)`, borderColor: `hsl(${hue(id)} 60% 55%)`, color: `hsl(${hue(id)} 60% 20%)` })
