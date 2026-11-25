import type { TaskType } from '../../datasets/annotation/store'
import type { Modality } from '../../datasets/mockData'
import type { CodeRef, CodeState, Member, Model, ModelFile, ModelVersion, VersionStatus } from '../types'
import type { WireCode, WireFile, WireMember, WireModel, WireModelSummary, WireVersion } from './wire'

export function toModel(wire: WireModelSummary | WireModel): Model {
  const full = wire as Partial<WireModel>
  return {
    id: wire.id,
    owner: wire.owner,
    name: wire.name,
    address: `${wire.owner}/${wire.name}`,
    description: wire.description,
    tasks: wire.tasks as TaskType[],
    inputs: wire.inputs as Modality[],
    library: wire.library,
    languages: wire.languages,
    license: wire.license,
    tags: wire.tags,
    visibility: wire.visibility,
    codeUrl: wire.code_url,
    parameters: wire.parameters,
    trainedOn: wire.trained_on,
    downloads: wire.downloads,
    likes: wire.likes,
    liked: wire.liked,
    version: wire.version,
    sizeBytes: wire.size_bytes,
    createdByUsername: wire.created_by_username,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
    card: full.card ?? '',
    canEdit: full.can_edit ?? false,
    mlflowUrl: full.mlflow_url ?? null,
    serving: full.serving ? { kind: full.serving.kind, input: full.serving.input as Modality, output: full.serving.output } : null,
  }
}

const toCode = (code: WireCode): CodeRef => ({
  url: code.url,
  ref: code.ref,
  refKind: code.ref_kind,
  path: code.path,
  entrypoint: code.entrypoint,
  sha: code.sha,
  state: code.state as CodeState,
  error: code.error,
  treeUrl: code.tree_url ?? null,
})

export const toVersion = (version: WireVersion): ModelVersion => ({
  number: version.number,
  status: version.status as VersionStatus,
  error: version.error,
  sizeBytes: version.size_bytes,
  message: version.message,
  servable: version.servable,
  code: version.code && toCode(version.code),
  createdByUsername: version.created_by_username,
  createdAt: version.created_at,
  mlflowUrl: version.mlflow_url ?? null,
})

export const toFile = (file: WireFile): ModelFile => ({
  path: file.path,
  sizeBytes: file.size_bytes,
  sha256: file.sha256,
  contentType: file.content_type,
})

export const toMember = (member: WireMember): Member => ({
  userId: member.user_id,
  role: member.role,
  addedBy: member.added_by,
  createdAt: member.created_at,
})
