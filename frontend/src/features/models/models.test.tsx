import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'
import type { WireCode, WireFile, WireVersion } from '@/features/models/api/wire'
import type { SeedModel } from '@/test/fakeModelsApi'
import { ada, bob, renderApp, Reply, stubBackend } from '@/test/render'

const NER: SeedModel = { owner: 'lab', name: 'ner-fr-v1', description: 'Named entities in French.', tasks: ['ner'], inputs: ['text'], tags: ['nlp'], downloads: 900, likes: 4, version: 2, size_bytes: 300 * 1024 ** 2, serving: { kind: 'mlflow', input: 'text', output: 'labels' }, mlflow_url: 'http://mlflow.test/#/models/lab~ner-fr-v1' }
const DETECTOR: SeedModel = { owner: 'lab', name: 'detector-v3', description: 'Boxes the objects of an image.', tasks: ['image_detection'], inputs: ['image'], downloads: 500, likes: 9 }
const SECRET: SeedModel = { owner: 'lab', name: 'secret', visibility: 'private', description: 'Not for you.' }
const MINE: SeedModel = { owner: 'bob', name: 'sentiment', description: 'Mine.', mlflow_url: 'http://mlflow.test/#/models/bob~sentiment' }

async function open(path: string, models: SeedModel[] = [NER, DETECTOR, SECRET, MINE], user: typeof bob | typeof ada = bob, partSize?: number) {
  const backend = stubBackend(user, undefined, { models, partSize })
  const router = renderApp(path)
  await screen.findByRole('button', { name: 'Open the user menu' })
  return { ...backend, router }
}

const card = (name: string) => screen.findByRole('link', { name: new RegExp(name) })

// ---- the list

it('lists the models the person can see, each with what the API says of it', async () => {
  await open('/models')
  const link = await card('lab/ner-fr-v1')
  expect(within(link).getByText('Entity extraction')).toBeInTheDocument()
  expect(within(link).getByText('v2')).toBeInTheDocument()
  expect(within(link).getByText('300 MB')).toBeInTheDocument()
  expect(screen.queryByText('lab/secret')).not.toBeInTheDocument() // private, and not theirs
  expect(await screen.findByText('3 models')).toBeInTheDocument()
})

it('asks the server for the kind of data, then for the task, and drops the task with its kind', async () => {
  const user = userEvent.setup()
  await open('/models')
  await card('lab/ner-fr-v1')
  await user.click(screen.getByRole('button', { name: 'Image' }))
  await waitFor(() => expect(screen.queryByRole('link', { name: /ner-fr-v1/ })).not.toBeInTheDocument())
  expect(screen.getByRole('link', { name: /detector-v3/ })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Object detection' }))
  expect(screen.getByRole('button', { name: 'Object detection' })).toHaveAttribute('aria-pressed', 'true')
  await user.click(screen.getByRole('button', { name: 'Text' })) // another kind: the task goes
  expect(await card('ner-fr-v1')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Object detection' })).not.toBeInTheDocument()
})

it('searches on the server and says so when nothing matches', async () => {
  const user = userEvent.setup()
  await open('/models')
  await card('ner-fr-v1')
  await user.type(screen.getByRole('textbox', { name: 'Search models…' }), 'boxes')
  expect(await card('detector-v3')).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByRole('link', { name: /ner-fr-v1/ })).not.toBeInTheDocument())
  await user.clear(screen.getByRole('textbox', { name: 'Search models…' }))
  await user.type(screen.getByRole('textbox', { name: 'Search models…' }), 'zzzz')
  expect(await screen.findByText('No model matches.')).toBeInTheDocument()
})

it('sorts by what the server counts, and shows the next page on request', async () => {
  const user = userEvent.setup()
  const many = Array.from({ length: 14 }, (_, i): SeedModel => ({ owner: 'lab', name: `m${String(i).padStart(2, '0')}`, downloads: 100 - i, likes: i }))
  await open('/models', many)
  await screen.findByRole('link', { name: /m00/ })
  expect(screen.getAllByRole('link', { name: /lab\/m/ })).toHaveLength(12)
  await user.click(screen.getByRole('button', { name: 'Show 2 more' }))
  expect(await screen.findByRole('link', { name: /m13/ })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Most liked' }))
  await waitFor(() => expect(screen.getAllByRole('link', { name: /lab\/m/ })[0]).toHaveTextContent('lab/m13'))
})

it('says what went wrong when the list cannot be read', async () => {
  stubBackend(bob, (url) => (url.startsWith('/api/models') ? new Reply(500) : undefined))
  renderApp('/models')
  expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
})

// ---- creating

it('creates a model in the name of the person, and opens its page', async () => {
  const user = userEvent.setup()
  const { models } = await open('/models')
  await user.click(await screen.findByRole('button', { name: 'New model' }))
  const dialog = await screen.findByRole('dialog')
  await user.type(within(dialog).getByLabelText('Name'), 'my-model')
  await user.click(within(dialog).getByRole('button', { name: 'Create' }))
  expect(await screen.findByRole('heading', { name: 'bob/my-model' })).toBeInTheDocument()
  expect(models.models.some((s) => s.model.name === 'my-model')).toBe(true)
})

it('says a name is taken, and keeps the dialog open', async () => {
  const user = userEvent.setup()
  await open('/models')
  await user.click(await screen.findByRole('button', { name: 'New model' }))
  const dialog = await screen.findByRole('dialog')
  await user.type(within(dialog).getByLabelText('Name'), 'sentiment')
  await user.click(within(dialog).getByRole('button', { name: 'Create' }))
  expect(await within(dialog).findByText('You already have a model with this name.')).toBeInTheDocument()
})

// ---- the page

it('shows a model with its card, its numbers and the way to try it', async () => {
  await open('/models/lab/ner-fr-v1')
  expect(await screen.findByRole('heading', { name: 'lab/ner-fr-v1' })).toBeInTheDocument()
  expect(screen.getByText('Named entities in French.')).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'Try it' })).toBeInTheDocument()
})

it('treats a private model that is not theirs as one that does not exist, never as forbidden', async () => {
  await open('/models/lab/secret')
  expect(await screen.findByRole('heading', { name: /not found|404/i })).toBeInTheDocument()
  expect(screen.queryByText(/denied|forbidden/i)).not.toBeInTheDocument()
  expect(screen.queryByText('Not for you.')).not.toBeInTheDocument()
})

it('treats a model that does not exist the same way', async () => {
  await open('/models/lab/nothing')
  expect(await screen.findByRole('heading', { name: /not found|404/i })).toBeInTheDocument()
})

it('likes and unlikes with the count the server gives back', async () => {
  const user = userEvent.setup()
  await open('/models/lab/ner-fr-v1')
  const heart = await screen.findByRole('button', { name: '4' })
  await user.click(heart)
  expect(await screen.findByRole('button', { name: '5' })).toHaveAttribute('aria-pressed', 'true')
  await user.click(screen.getByRole('button', { name: '5' }))
  expect(await screen.findByRole('button', { name: '4' })).toHaveAttribute('aria-pressed', 'false')
})

// ---- MLflow

it('gives the people who can edit a link to MLflow that opens in a new tab and cannot reach back', async () => {
  await open('/models/bob/sentiment')
  const link = await screen.findByRole('link', { name: 'Open in MLflow' })
  expect(link).toHaveAttribute('href', 'http://mlflow.test/#/models/bob~sentiment')
  expect(link).toHaveAttribute('target', '_blank')
  expect(link).toHaveAttribute('rel', 'noopener noreferrer')
})

it('renders nothing of MLflow for a reader', async () => {
  const { container } = (await open('/models/lab/ner-fr-v1')) as unknown as { container?: HTMLElement }
  await screen.findByRole('heading', { name: 'lab/ner-fr-v1' })
  expect(screen.queryByRole('link', { name: /MLflow/ })).not.toBeInTheDocument()
  expect(document.body.innerHTML).not.toContain('mlflow.test')
  void container
})

// ---- versions

type StoredVersion = WireVersion & { files: WireFile[] }
const VERSIONS = (state: Partial<StoredVersion>[]): StoredVersion[] =>
  state.map((v, i) => ({ number: i + 1, status: 'ready', error: null, size_bytes: 1024 ** 2, message: `change ${i + 1}`, servable: false, code: null, created_by: 'u', created_by_username: 'bob', created_at: '2026-11-01T09:00:00Z', files: [], ...v }))

const code = (state: string, extra: Partial<WireCode> = {}): WireCode => ({ url: 'https://github.com/o/r', ref: 'main', ref_kind: 'branch', path: 'src', entrypoint: null, sha: null, state, error: null, tree_url: null, ...extra })

it('shows a version being checked, and the reason one failed', async () => {
  const user = userEvent.setup()
  const { models } = await open('/models/lab/detector-v3')
  models.models[1].versions.push(...VERSIONS([{ status: 'ready' }, { status: 'pending' }, { status: 'failed', error: 'The file is not a model' }]))
  await user.click(await screen.findByRole('tab', { name: 'Versions' }))
  expect(await screen.findByText('checking')).toBeInTheDocument()
  expect(screen.getByText('failed')).toBeInTheDocument()
  expect(screen.getByRole('alert')).toHaveTextContent('The file is not a model')
  expect(screen.getByText('ready')).toBeInTheDocument()
})

it('links a pinned code reference to the exact tree, and says "not pinned" or "not verified" before that', async () => {
  const user = userEvent.setup()
  const { models } = await open('/models/lab/detector-v3')
  const sha = 'a'.repeat(40)
  models.models[1].versions.push(...VERSIONS([
    { code: code('pinned', { sha, tree_url: `https://github.com/o/r/tree/${sha}/src` }) },
    { code: code('unresolved') },
    { code: code('unverified', { error: 'private' }) },
  ]))
  await user.click(await screen.findByRole('tab', { name: 'Versions' }))
  const link = await screen.findByRole('link', { name: new RegExp(sha.slice(0, 12)) })
  expect(link).toHaveAttribute('href', `https://github.com/o/r/tree/${sha}/src`)
  expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  expect(screen.getByText('pinned')).toBeInTheDocument()
  expect(screen.getByText('not pinned')).toBeInTheDocument()
  expect(screen.getByText('not verified')).toBeInTheDocument()
  // A branch that is not pinned is text, not a link as if it were fixed.
  expect(screen.queryByRole('link', { name: /@ main/ })).not.toBeInTheDocument()
  expect(screen.getAllByText(/github.com\/o\/r @ main/)).toHaveLength(2)
})

it('lists the files of a version with an address to download each', async () => {
  const user = userEvent.setup()
  const { models } = await open('/models/lab/detector-v3')
  models.models[1].versions.push(...VERSIONS([{ files: [{ path: 'weights/model.safetensors', size_bytes: 2 * 1024 ** 2, sha256: null, content_type: 'x' }] }]))
  await user.click(await screen.findByRole('tab', { name: 'Files' }))
  const download = await screen.findByRole('link', { name: 'Download weights/model.safetensors' })
  expect(download).toHaveAttribute('href', '/api/models/lab/detector-v3/files/weights/model.safetensors?version=1')
})

it('lets an editor delete a version after a second click', async () => {
  const user = userEvent.setup()
  const { models } = await open('/models/bob/sentiment')
  models.models[3].versions.push(...VERSIONS([{}]))
  await user.click(await screen.findByRole('tab', { name: 'Versions' }))
  await user.click(await screen.findByRole('button', { name: 'Delete version 1' }))
  await user.click(screen.getByRole('button', { name: 'Delete this version' }))
  expect(await screen.findByText('No version yet.')).toBeInTheDocument()
})

// ---- try it

it('does not offer to try a model that is not served', async () => {
  await open('/models/lab/detector-v3')
  await screen.findByRole('heading', { name: 'lab/detector-v3' })
  expect(screen.queryByRole('tab', { name: 'Try it' })).not.toBeInTheDocument()
})

it('tries a text through the relay and shows the labels it gives back', async () => {
  const user = userEvent.setup()
  const { models } = await open('/models/lab/ner-fr-v1')
  models.predict = (input) => [{ label: `got:${String(input).slice(0, 5)}`, score: 0.9 }, { label: 'other', score: 0.1 }]
  await user.click(await screen.findByRole('tab', { name: 'Try it' }))
  const box = screen.getByRole('textbox', { name: 'Text to analyse' })
  await user.clear(box)
  await user.type(box, 'hello world')
  await user.click(screen.getByRole('button', { name: 'Run' }))
  expect(await screen.findByText('got:hello')).toBeInTheDocument()
  expect(screen.getByText('90 %')).toBeInTheDocument()
  expect(screen.getByText('Answered in 12 ms.')).toBeInTheDocument()
})

it.each([
  [409, 'This model is not served any more.'],
  [429, 'Too many tries: wait a moment.'],
  [503, 'The server of the model does not answer.'],
  [504, 'The model took too long to answer.'],
  [502, 'The model answered something that cannot be read.'],
  [413, 'This input is too large.'],
  [422, 'The model cannot take this input.'],
])('says in a sentence what the relay answered when it is %i', async (status, sentence) => {
  const user = userEvent.setup()
  const { models } = await open('/models/lab/ner-fr-v1')
  models.predict = () => new Reply(status, { detail: 'x' })
  await user.click(await screen.findByRole('tab', { name: 'Try it' }))
  await user.click(screen.getByRole('button', { name: 'Run' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(sentence)
})

it('takes a JSON input for a model that does not read text, and refuses what is not JSON', async () => {
  const user = userEvent.setup()
  const { models } = await open('/models/lab/tab', [{ ...NER, name: 'tab', inputs: ['tabular'], serving: { kind: 'custom', input: 'tabular', output: 'json' } }])
  let seen: unknown
  models.predict = (input) => { seen = input; return { echoed: true } }
  await user.click(await screen.findByRole('tab', { name: 'Try it' }))
  const box = screen.getByRole('textbox', { name: 'Input (JSON)' })
  await user.type(box, 'not json')
  await user.click(screen.getByRole('button', { name: 'Run' }))
  expect(await screen.findByText('This is not valid JSON.')).toBeInTheDocument()
  expect(seen).toBeUndefined()
  await user.clear(box)
  await user.click(box)
  await user.paste('{"a": [1, 2]}')
  await user.click(screen.getByRole('button', { name: 'Run' }))
  expect(await screen.findByText(/"echoed": true/)).toBeInTheDocument()
  expect(seen).toEqual({ a: [1, 2] })
})

// ---- who has access

it('lists, adds and takes away access for the people who can edit', async () => {
  const user = userEvent.setup()
  await open('/models/bob/sentiment')
  await user.click(await screen.findByRole('button', { name: 'Access' }))
  const dialog = await screen.findByRole('dialog')
  expect(await within(dialog).findByText('Nobody else has access.')).toBeInTheDocument()
  await user.type(within(dialog).getByRole('textbox', { name: 'User id' }), 'carol')
  await user.click(within(dialog).getByRole('button', { name: 'Give access' }))
  expect(await within(dialog).findByText('carol')).toBeInTheDocument()
  await user.click(within(dialog).getByRole('button', { name: 'Take away the access of carol' }))
  expect(await within(dialog).findByText('Nobody else has access.')).toBeInTheDocument()
})

it('offers a reader neither an upload, nor access, nor deletion', async () => {
  await open('/models/lab/ner-fr-v1')
  await screen.findByRole('heading', { name: 'lab/ner-fr-v1' })
  expect(screen.queryByRole('button', { name: 'New version' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Access' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
})

it('deletes a model after a second click and goes back to the list', async () => {
  const user = userEvent.setup()
  const { models, router } = await open('/models/bob/sentiment')
  await user.click(await screen.findByRole('button', { name: 'Delete' }))
  await user.click(screen.getByRole('button', { name: 'Delete for good' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/models'))
  expect(models.models.some((s) => s.model.name === 'sentiment')).toBe(false)
})
