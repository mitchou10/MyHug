export type Scope = 'read' | 'write'

export interface AccessToken {
  id: string
  name: string
  scope: Scope
  /** The first characters: all that can be read of a token afterwards. */
  prefix: string
  createdAt: string
  expiresAt: string | null
  lastUsedAt: string | null
  revokedAt: string | null
}

export interface NewToken {
  name: string
  scope: Scope
  /** Empty: it does not expire. */
  expiresInDays: number | null
}

/** The answer to making a token: the only time its secret is known. */
export interface CreatedToken extends AccessToken {
  secret: string
}

export type TokenState = 'active' | 'revoked' | 'expired'

export const stateOf = (token: AccessToken, now = Date.now()): TokenState =>
  token.revokedAt ? 'revoked' : token.expiresAt && Date.parse(token.expiresAt) <= now ? 'expired' : 'active'
