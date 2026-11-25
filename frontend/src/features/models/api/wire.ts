import type { components } from '@/lib/schema'

/** The shapes the backend sends (snake_case): generated from its OpenAPI schema (`pnpm generate:api`). Only the mappers read them. */
type S = components['schemas']

export interface WirePage<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type WireModelSummary = S['ModelSummaryOut']
export type WireModel = S['ModelOut']
export type WireCode = S['CodeOut']
export type WireVersion = S['ModelVersionOut']
export type WireFile = S['ModelFileOut']
export type WireVersionDetail = S['ModelVersionDetailOut']
export type WireMember = S['MemberOut']
export type WireUploadFile = S['UploadFileOut']
export type WireUpload = S['UploadOut']
export type WirePredict = S['PredictOut']
export type WireEvaluation = S['EvaluationOut']
export type WireTaskMetrics = S['TaskMetricsOut']
