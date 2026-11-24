import { MODELS } from '../datasets/annotation/models'

/** How good a known model is, for the simulation of its metrics. */
export const ANNOTATION_QUALITY = (name: string) => MODELS.find((m) => m.id === name)?.quality ?? 0.7
