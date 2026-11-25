/** The shapes the backend sends (snake_case): generated from its OpenAPI schema (`pnpm generate:api`). Only the mappers read them. */

import type { components } from '@/lib/schema'
import type { Tone } from '../types'

type S = components['schemas']

export type WireAttachment = S['AttachmentOut']

/** The schema says `tone` is a string: the screens only know these. */
export type WireReference = Omit<S['FeedbackTypeOut'], 'tone'> & { tone: Tone }

export type WireStatus = Omit<S['FeedbackStatusOut'], 'tone'> & { tone: Tone }

export type WireSummary = S['FeedbackSummaryOut']

export type WireFeedback = S['FeedbackOut']

export type WireMessage = Omit<S['MessageOut'], 'kind'> & { kind: 'comment' | 'status_change' }

export interface WirePage<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type WireMessagesPage = Omit<S['MessagesPageOut'], 'items'> & { items: WireMessage[] }
