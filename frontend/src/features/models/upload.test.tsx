import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it } from 'vitest'
import type { SeedModel } from '@/test/fakeModelsApi'
import { bob, renderApp, Reply, stubBackend } from '@/test/render'

const MINE: SeedModel = { owner: 'bob', name: 'sentiment', description: 'Mine.' }
const SLOT = 'myhug.model-upload.bob/sentiment'

beforeEach(() => localStorage.clear())

async function openDialog() {
  const user = userEvent.setup()
  const backend = stubBackend(bob, undefined, { models: [MINE], partSize: 4 })
  renderApp('/models/bob/sentiment')
  await user.click(await screen.findByRole('button', { name: 'New version' }))
  return { user, backend, dialog: await screen.findByRole('dialog') }
}

const choose = (user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement, ...files: File[]) =>
  user.upload(within(dialog).getByLabelText('Choose files', { selector: 'input' }), files)

const weights = (size = 10, name = 'weights.bin') => new File([new Uint8Array(size)], name)

it('sends the files in parts to the storage, completes, and says the version is being checked', async () => {
  const { user, backend, dialog } = await openDialog()
  await choose(user, dialog, weights())
  expect(within(dialog).getByText('weights.bin')).toBeInTheDocument()
  await user.type(within(dialog).getByLabelText('What changed'), 'first weights')
  await user.click(within(dialog).getByRole('button', { name: 'Send' }))
  expect(await within(dialog).findByText('Version 1 was created. Its files are being checked.')).toBeInTheDocument()
  expect(backend.models.sentParts).toHaveLength(3) // 10 bytes in parts of 4
  expect(backend.models.models[0].versions[0]).toMatchObject({ status: 'pending', message: 'first weights' })
  expect(localStorage.getItem(SLOT)).toBeNull() // nothing left to resume
})

it('shows the new version in the list once the upload is done', async () => {
  const { user, dialog } = await openDialog()
  await choose(user, dialog, weights())
  await user.click(within(dialog).getByRole('button', { name: 'Send' }))
  await within(dialog).findByText(/Version 1 was created/)
  await user.keyboard('{Escape}')
  await user.click(await screen.findByRole('tab', { name: 'Versions' }))
  expect(await screen.findByText('checking')).toBeInTheDocument()
})

it('removes a file that was chosen by mistake, and sends nothing until there is something to send', async () => {
  const { user, dialog } = await openDialog()
  expect(within(dialog).getByRole('button', { name: 'Send' })).toBeDisabled()
  await choose(user, dialog, weights())
  await user.click(within(dialog).getByRole('button', { name: 'Remove weights.bin' }))
  expect(within(dialog).queryByText('weights.bin')).not.toBeInTheDocument()
  expect(within(dialog).getByRole('button', { name: 'Send' })).toBeDisabled()
})

it('says which part did not arrive, keeps the others, and goes on when asked', async () => {
  const { user, backend, dialog } = await openDialog()
  backend.models.refuseParts(100)
  await choose(user, dialog, weights())
  await user.click(within(dialog).getByRole('button', { name: 'Send' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(/Part \d of weights.bin did not reach the storage/)
  backend.models.refuseParts(0)
  const resume = await within(dialog).findByRole('button', { name: 'Go on' })
  await waitFor(() => expect(resume).toBeEnabled())
  await user.click(resume)
  expect(await within(dialog).findByText(/Version 1 was created/)).toBeInTheDocument()
})

it('finds an interrupted upload after a reload and goes on from the parts that arrived', async () => {
  const user = userEvent.setup()
  const backend = stubBackend(bob, undefined, { models: [MINE], partSize: 4 })
  // Before the reload: announced, one part of three arrived, the id was kept in the browser.
  const started = backend.models.handle('/api/models/bob/sentiment/uploads', { method: 'POST', body: JSON.stringify({ files: [{ path: 'weights.bin', size: 10 }], remove: [], message: 'm', code: null }) })!
  const upload = started.body as { id: string; files: { id: string }[] }
  backend.models.handle(`https://storage.test/${upload.id}/${upload.files[0].id}/1`, { method: 'PUT', body: new Blob(['abcd']) })
  localStorage.setItem(SLOT, upload.id)

  renderApp('/models/bob/sentiment')
  await user.click(await screen.findByRole('button', { name: 'New version' }))
  const dialog = await screen.findByRole('dialog')
  expect(await within(dialog).findByText('An upload of 1 file was interrupted.')).toBeInTheDocument()
  expect(within(dialog).getByRole('button', { name: 'Go on' })).toBeDisabled() // the files are chosen again first
  await choose(user, dialog, weights())
  await user.click(within(dialog).getByRole('button', { name: 'Go on' }))
  expect(await within(dialog).findByText(/Version 1 was created/)).toBeInTheDocument()
  expect(backend.models.sentParts.filter((a) => a.startsWith('https://storage.test/') && a.endsWith('/1'))).toHaveLength(1) // only the one put by hand
  expect(backend.models.sentParts).toHaveLength(3) // that one, and parts 2 and 3
})

it('does not send files that are not the ones that were announced', async () => {
  const user = userEvent.setup()
  const backend = stubBackend(bob, undefined, { models: [MINE], partSize: 4 })
  const started = backend.models.handle('/api/models/bob/sentiment/uploads', { method: 'POST', body: JSON.stringify({ files: [{ path: 'weights.bin', size: 10 }], remove: [], message: '', code: null }) })!
  localStorage.setItem(SLOT, (started.body as { id: string }).id)
  renderApp('/models/bob/sentiment')
  await user.click(await screen.findByRole('button', { name: 'New version' }))
  const dialog = await screen.findByRole('dialog')
  await choose(user, dialog, weights(11))
  await user.click(await within(dialog).findByRole('button', { name: 'Go on' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('weights.bin is not the file that was announced.')
  expect(backend.models.sentParts).toHaveLength(0)
})

it('gives an interrupted upload up: what arrived is thrown away and nothing is kept in the browser', async () => {
  const user = userEvent.setup()
  const backend = stubBackend(bob, undefined, { models: [MINE], partSize: 4 })
  const started = backend.models.handle('/api/models/bob/sentiment/uploads', { method: 'POST', body: JSON.stringify({ files: [{ path: 'weights.bin', size: 10 }], remove: [], message: '', code: null }) })!
  localStorage.setItem(SLOT, (started.body as { id: string }).id)
  renderApp('/models/bob/sentiment')
  await user.click(await screen.findByRole('button', { name: 'New version' }))
  const dialog = await screen.findByRole('dialog')
  await user.click(await within(dialog).findByRole('button', { name: 'Give up' }))
  await waitFor(() => expect(backend.models.uploads[0].upload.status).toBe('aborted'))
  expect(localStorage.getItem(SLOT)).toBeNull()
  expect(within(dialog).queryByText(/was interrupted/)).not.toBeInTheDocument()
})

it('forgets an upload that the server does not know any more', async () => {
  const user = userEvent.setup()
  stubBackend(bob, undefined, { models: [MINE] })
  localStorage.setItem(SLOT, 'gone')
  renderApp('/models/bob/sentiment')
  await user.click(await screen.findByRole('button', { name: 'New version' }))
  await waitFor(() => expect(localStorage.getItem(SLOT)).toBeNull())
})

it('makes a version of a link to the code alone, which is not pinned yet', async () => {
  const { user, dialog } = await openDialog()
  await user.type(within(dialog).getByLabelText('Address of the repository'), 'https://github.com/o/r')
  await user.type(within(dialog).getByLabelText('Branch, tag or commit'), 'main')
  await user.click(within(dialog).getByRole('button', { name: 'Send' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  await user.click(await screen.findByRole('tab', { name: 'Versions' }))
  expect(await screen.findByText('not pinned')).toBeInTheDocument()
  expect(screen.getByText('https://github.com/o/r @ main')).toBeInTheDocument()
})

it('says what the API answered when the upload cannot start', async () => {
  const { user, backend, dialog } = await openDialog()
  backend.models.announcement = new Reply(422, { detail: 'The paths are not valid' })
  await choose(user, dialog, weights())
  await user.click(within(dialog).getByRole('button', { name: 'Send' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Something is missing or not valid')
  expect(backend.models.sentParts).toHaveLength(0)
})
