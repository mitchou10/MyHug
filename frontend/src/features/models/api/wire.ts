/** The shapes the backend sends (snake_case). Only the mappers read them. */

export interface WirePage<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface WireModelSummary {
  id: string
  owner: string
  name: string
  description: string
  tasks: string[]
  inputs: string[]
  library: string
  languages: string[]
  license: string
  tags: string[]
  visibility: 'public' | 'private'
  code_url: string | null
  parameters: number | null
  trained_on: string[]
  downloads: number
  likes: number
  liked: boolean
  version: number
  size_bytes: number
  created_by: string
  created_by_username: string
  created_at: string
  updated_at: string
}

export interface WireModel extends WireModelSummary {
  card: string
  can_edit: boolean
  mlflow_url?: string | null
  serving: { kind: 'mlflow' | 'custom'; input: string; output: 'labels' | 'boxes' | 'text' | 'values' | 'json' } | null
}

export interface WireCode {
  url: string
  ref: string | null
  ref_kind: string
  path: string | null
  entrypoint: string | null
  sha: string | null
  state: string
  error: string | null
  tree_url: string | null
}

export interface WireVersion {
  number: number
  status: string
  error: string | null
  size_bytes: number
  message: string
  servable: boolean
  code: WireCode | null
  created_by: string
  created_by_username: string
  created_at: string
  mlflow_url?: string | null
}

export interface WireFile {
  path: string
  size_bytes: number
  sha256: string | null
  content_type: string
}

export interface WireVersionDetail extends WireVersion {
  files: WireFile[]
}

export interface WireMember {
  user_id: string
  role: 'reader' | 'maintainer'
  added_by: string
  created_at: string
}

export interface WireUploadFile {
  id: string
  path: string
  size_bytes: number
  part_size: number
  parts_count: number
  already_stored: boolean
  received: { number: number; size: number }[] | null
}

export interface WireUpload {
  id: string
  status: 'open' | 'completed' | 'aborted' | 'expired'
  expires_at: string
  version: number | null
  files: WireUploadFile[]
}

export interface WirePredict {
  output: unknown
  took_ms: number
}
