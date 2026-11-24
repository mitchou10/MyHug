import { seeded } from '../datasets/components/viewers/seed'
import { MODELS as ANNOTATION_MODELS } from '../datasets/annotation/models'
import type { TaskType } from '../datasets/annotation/store'
import type { Modality } from '../datasets/mockData'

/** Temporary mock data: replaced by the API once the backend handles models. */
export interface ModelVersion { version: string; date: string; sizeMb: number; changelog: 'first' | 'better' | 'faster' | 'latest' }

export interface Model {
  id: string
  owner: string
  /** The name of the model: also the one used by the pre-annotation. */
  name: string
  /** What the author wrote; without it, the description of the known model is used. */
  description?: string
  /** The kinds of annotation tasks the model can pre-annotate: it is what makes it a model for one kind of data or another. */
  tasks: TaskType[]
  inputs: Modality[]
  languages: string[]
  license: string
  tags: string[]
  paramsM: number
  sizeMb: number
  downloads: number
  likes: number
  updatedAt: string
  version: string
  versions: ModelVersion[]
  files: { path: string; sizeMb: number }[]
  /** The datasets (`owner/name`) it was trained on. */
  trainedOn: string[]
  visibility: 'public' | 'private'
}

// id, owner, kind of data, languages, license, tags, datasets it was trained on
const ENTRIES: [string, string, Modality, string[], string, string[], string[]][] = [
  ['sentiment-fr-v2', 'mitchou', 'text', ['fr'], 'apache-2.0', ['sentiment', 'nlp'], ['mitchou/movie-reviews-fr']],
  ['zero-shot-text', 'lab', 'text', ['multilingual'], 'mit', ['zero-shot', 'nlp'], []],
  ['ner-fr-v1', 'lab', 'text', ['fr'], 'apache-2.0', ['ner', 'nlp'], ['lab/decisions-justice']],
  ['ner-legal-v1', 'lab', 'text', ['fr'], 'etalab-2.0', ['juridique', 'ner'], ['lab/decisions-justice']],
  ['qa-extractive-v1', 'lab', 'text', ['en', 'fr'], 'apache-2.0', ['qa', 'nlp'], ['lab/qa-instructions']],
  ['tabular-quality-v1', 'mitchou', 'tabular', [], 'mit', ['qualité des données'], ['mitchou/house-prices']],
  ['schema-guesser-v1', 'mitchou', 'tabular', [], 'mit', ['schéma'], []],
  ['regressor-base-v1', 'mitchou', 'tabular', [], 'mit', ['régression'], ['mitchou/house-prices']],
  ['detector-v3', 'lab', 'image', [], 'agpl-3.0', ['vision', 'détection'], ['mitchou/street-signs']],
  ['segmenter-sam-lite', 'lab', 'image', [], 'apache-2.0', ['vision', 'segmentation'], []],
  ['pose-v1', 'lab', 'image', [], 'mit', ['vision', 'pose'], []],
  ['scene-clip-v1', 'lab', 'image', [], 'mit', ['vision', 'clip'], ['mitchou/street-signs']],
  ['captioner-v2', 'lab', 'image', ['en', 'fr'], 'apache-2.0', ['vision', 'description'], []],
  ['birdnet-lite', 'mitchou', 'audio', [], 'cc-by-nc-4.0', ['audio', 'biodiversité'], ['mitchou/bird-sounds']],
  ['diarizer-v1', 'lab', 'audio', ['fr', 'en'], 'mit', ['parole', 'locuteurs'], ['lab/call-center-fr']],
  ['speech-to-text-v3', 'lab', 'audio', ['fr'], 'apache-2.0', ['parole', 'asr'], ['lab/call-center-fr']],
  ['audio-caption-v1', 'lab', 'audio', ['en'], 'mit', ['audio'], []],
  ['action-seg-v1', 'lab', 'video', [], 'apache-2.0', ['vidéo', 'actions'], ['lab/kitchen-actions']],
  ['tracker-v2', 'lab', 'video', [], 'mit', ['vidéo', 'suivi'], ['lab/kitchen-actions']],
  ['video-caption-v1', 'lab', 'video', ['en'], 'mit', ['vidéo'], []],
  ['anomaly-v1', 'lab', 'timeseries', [], 'apache-2.0', ['anomalies', 'séries'], ['lab/sales-timeseries']],
  ['ts-classifier-v1', 'lab', 'timeseries', [], 'mit', ['séries'], ['lab/sales-timeseries']],
  ['forecaster-v1', 'lab', 'timeseries', [], 'apache-2.0', ['prévision', 'séries'], ['lab/sales-timeseries']],
]

function build([name, owner, input, languages, license, tags, trainedOn]: (typeof ENTRIES)[number]): Model {
  const rnd = seeded(name)
  const info = ANNOTATION_MODELS.find((m) => m.id === name)
  const tasks = info?.tasks ?? []
  const sizeMb = Math.round(20 + rnd() * 900)
  const day = (n: number) => `2026-${String(11 - Math.floor(n / 30)).padStart(2, '0')}-${String(28 - (n % 28)).padStart(2, '0')}`
  const latest = `${1 + Math.floor(rnd() * 2)}.${Math.floor(rnd() * 4)}.0`
  return {
    id: `${owner}/${name}`, owner, name, tasks, inputs: [input], languages, license, tags, trainedOn,
    paramsM: Math.round(5 + rnd() * 300), sizeMb, downloads: Math.round(200 + rnd() * 9000), likes: Math.round(3 + rnd() * 180), updatedAt: day(Math.floor(rnd() * 60)),
    version: latest,
    versions: [
      { version: '1.0.0', date: '2026-08-14', sizeMb: Math.round(sizeMb * 0.9), changelog: 'first' },
      { version: '1.1.0', date: '2026-09-30', sizeMb: Math.round(sizeMb * 0.95), changelog: 'better' },
      ...(latest === '1.1.0' ? [] : [{ version: latest, date: '2026-11-05', sizeMb, changelog: 'latest' as const }]),
    ],
    files: [{ path: 'README.md', sizeMb: 0.01 }, { path: 'config.json', sizeMb: 0.01 }, { path: 'model.safetensors', sizeMb }, { path: 'tokenizer.json', sizeMb: 2 }],
    visibility: 'public',
  }
}

export const MODEL_HUB: Model[] = ENTRIES.map(build)

/** The kinds of data a model can read, in the order of the filters. */
export const INPUTS: Modality[] = ['text', 'image', 'audio', 'video', 'tabular', 'timeseries']
