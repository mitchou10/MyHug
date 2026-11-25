import type { TaskType } from '../datasets/annotation/store'
import type { Modality } from '../datasets/mockData'

/** The kinds of data a model can read, in the order of the filters. */
export const INPUTS: Modality[] = ['text', 'image', 'audio', 'video', 'tabular', 'timeseries']

export type Visibility = 'public' | 'private'

/** What can be tried, for everybody: what the model takes and gives, never where it is. */
export interface Serving {
  kind: 'mlflow' | 'custom'
  input: Modality
  output: 'labels' | 'boxes' | 'text' | 'values' | 'json'
}

/** A model, as the list and the page show it. */
export interface Model {
  id: string
  owner: string
  name: string
  /** `owner/name`: how a model is named everywhere. */
  address: string
  description: string
  tasks: TaskType[]
  inputs: Modality[]
  library: string
  languages: string[]
  license: string
  tags: string[]
  visibility: Visibility
  codeUrl: string | null
  parameters: number | null
  trainedOn: string[]
  downloads: number
  likes: number
  liked: boolean
  /** The number of the latest version: 0 for a model that has none. */
  version: number
  sizeBytes: number
  createdByUsername: string
  createdAt: string
  updatedAt: string
  /** Only on the page of a model. */
  card: string
  canEdit: boolean
  /** Only for the people who can edit the model: nobody else is given it. */
  mlflowUrl: string | null
  serving: Serving | null
}

export type CodeState = 'unresolved' | 'resolving' | 'pinned' | 'unverified' | 'failed'

export interface CodeRef {
  url: string
  ref: string | null
  refKind: string
  path: string | null
  entrypoint: string | null
  sha: string | null
  state: CodeState
  error: string | null
  /** The page of the code at the exact commit: there only once it is pinned. */
  treeUrl: string | null
}

export type VersionStatus = 'pending' | 'processing' | 'ready' | 'failed'

export interface ModelVersion {
  number: number
  status: VersionStatus
  error: string | null
  sizeBytes: number
  message: string
  servable: boolean
  code: CodeRef | null
  createdByUsername: string
  createdAt: string
  mlflowUrl: string | null
}

export interface ModelFile {
  path: string
  sizeBytes: number
  sha256: string | null
  contentType: string
}

export interface Member {
  userId: string
  role: 'reader' | 'maintainer'
  addedBy: string
  createdAt: string
}

/** What the filters of the list send to the API. */
export interface ModelFilters {
  q: string
  modality: Modality | null
  task: TaskType | null
  sort: 'downloads' | 'likes' | 'updated'
}

export const NO_FILTERS: ModelFilters = { q: '', modality: null, task: null, sort: 'downloads' }
