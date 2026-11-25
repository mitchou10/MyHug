import type { components } from '@/lib/schema'

/** What the backend sends (snake_case): generated from its OpenAPI schema (`pnpm generate:api`). Only the mapper reads it. */
export type WireNotification = components['schemas']['NotificationOut']

export interface WirePage<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}
