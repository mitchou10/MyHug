import type { components } from '@/lib/schema'

/** What the backend sends (snake_case): generated from its OpenAPI schema. */
export type WireToken = components['schemas']['AccessTokenOut']
export type WireCreatedToken = components['schemas']['CreatedAccessTokenOut']
