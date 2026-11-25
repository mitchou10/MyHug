import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { bob, renderApp, Reply, stubBackend } from '@/test/render'

async function open() {
  const user = userEvent.setup()
  const backend = stubBackend(bob)
  const router = renderApp('/tokens')
  await screen.findByRole('heading', { name: 'Access tokens' })
  return { user, backend, router }
}

async function make(user: ReturnType<typeof userEvent.setup>, name: string, scope: 'Read' | 'Read and write' = 'Read') {
  await user.click(screen.getByRole('button', { name: 'New token' }))
  const dialog = await screen.findByRole('dialog')
  await user.type(within(dialog).getByLabelText('Name'), name)
  await user.click(within(dialog).getByRole('radio', { name: scope === 'Read' ? /^Read(?! and)/ : /^Read and write/ }))
  await user.click(within(dialog).getByRole('button', { name: 'Make the token' }))
  return dialog
}

it('is in the sidebar and opens the page', async () => {
  stubBackend(bob)
  renderApp('/app')
  const link = await screen.findByRole('link', { name: 'Access tokens' })
  await userEvent.click(link)
  expect(await screen.findByRole('heading', { name: 'Access tokens' })).toBeInTheDocument()
})

it('says so when there is no token', async () => {
  await open()
  expect(await screen.findByText('You have no access token.')).toBeInTheDocument()
})

it('makes a token, shows it once, and only the first characters after that', async () => {
  const { user, backend } = await open()
  const dialog = await make(user, 'training job', 'Read and write')
  const secret = (await within(dialog).findByLabelText('Token')) as HTMLInputElement
  expect(secret.value).toMatch(/^mh_/)
  expect(within(dialog).getByRole('alert')).toHaveTextContent('shown only once')
  const shown = secret.value

  await user.click(within(dialog).getByRole('button', { name: 'Done' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  const row = (await screen.findByText('training job')).closest('tr')!
  expect(within(row).getByText('Read and write')).toBeInTheDocument()
  expect(within(row).getByText(`${shown.slice(0, 11)}…`)).toBeInTheDocument()
  expect(within(row).getByText('never')).toBeInTheDocument() // not used yet
  expect(document.body.textContent).not.toContain(shown) // the page cannot give it back
  expect(backend.tokens.tokens).toHaveLength(1)
})

it('forgets the token when the dialog closes, so it is not there when it opens again', async () => {
  const { user } = await open()
  const dialog = await make(user, 'one')
  await within(dialog).findByLabelText('Token')
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'New token' }))
  const again = await screen.findByRole('dialog')
  expect(within(again).queryByLabelText('Token')).not.toBeInTheDocument()
  expect(within(again).getByLabelText('Name')).toHaveValue('')
})

it('copies the token', async () => {
  const user = userEvent.setup()
  stubBackend(bob)
  const writeText = vi.fn(async () => undefined)
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  renderApp('/tokens')
  await screen.findByRole('heading', { name: 'Access tokens' })
  const dialog = await make(user, 'copy me')
  const secret = (await within(dialog).findByLabelText('Token')) as HTMLInputElement
  await user.click(within(dialog).getByRole('button', { name: 'Copy' }))
  expect(writeText).toHaveBeenCalledWith(secret.value)
  expect(await within(dialog).findByRole('button', { name: 'Copied' })).toBeInTheDocument()
})

it('does not make a token without a name', async () => {
  const { user } = await open()
  await user.click(screen.getByRole('button', { name: 'New token' }))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByRole('button', { name: 'Make the token' })).toBeDisabled()
})

it('says what went wrong when the token cannot be made', async () => {
  const { user, backend } = await open()
  backend.tokens.refuseNext = new Reply(409, { detail: 'Too many access tokens: revoke one first' })
  await make(user, 'one')
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  expect(screen.getByRole('dialog')).toBeInTheDocument() // what was typed is kept
})

it('revokes a token after a second click, and it stays in the list as revoked', async () => {
  const { user, backend } = await open()
  const dialog = await make(user, 'old laptop')
  await user.click(await within(dialog).findByRole('button', { name: 'Done' }))
  await user.click(await screen.findByRole('button', { name: 'Revoke old laptop' }))
  expect(backend.tokens.tokens[0].revoked_at).toBeNull() // one click is not enough
  await user.click(screen.getByRole('button', { name: 'Revoke for good' }))
  const row = (await screen.findByText('old laptop')).closest('tr')!
  expect(await within(row).findByText('revoked')).toBeInTheDocument()
  expect(within(row).queryByRole('button')).not.toBeInTheDocument() // nothing more to do with it
  expect(backend.tokens.tokens[0].revoked_at).not.toBeNull()
})

it('shows an expired token as expired and gives no way to revoke it', async () => {
  const { backend } = await (async () => {
    const backend = stubBackend(bob)
    backend.tokens.tokens.push({ id: 't', name: 'ancient', scope: 'read', prefix: 'mh_aaaaaaaa', created_at: '2020-01-01T00:00:00Z', expires_at: '2020-02-01T00:00:00Z', last_used_at: '2020-01-15T00:00:00Z', revoked_at: null, owner: bob.user_id })
    renderApp('/tokens')
    return { backend }
  })()
  const row = (await screen.findByText('ancient')).closest('tr')!
  expect(within(row).getByText('expired')).toBeInTheDocument()
  expect(within(row).queryByRole('button')).not.toBeInTheDocument()
  expect(backend.tokens.tokens).toHaveLength(1)
})

it('lists only my tokens', async () => {
  const backend = stubBackend(bob)
  backend.tokens.tokens.push({ id: 'x', name: 'somebody elses', scope: 'read', prefix: 'mh_bbbbbbbb', created_at: '2026-11-01T00:00:00Z', expires_at: null, last_used_at: null, revoked_at: null, owner: 'other' })
  renderApp('/tokens')
  expect(await screen.findByText('You have no access token.')).toBeInTheDocument()
})
