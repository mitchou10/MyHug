import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'
import type { SeedModel } from '@/test/fakeModelsApi'
import { ada, bob, renderApp, Reply, stubBackend } from '@/test/render'

const NER: SeedModel = { owner: 'lab', name: 'ner-fr-v1', tasks: ['classification', 'regression'], inputs: ['text'], version: 1 }
const MINE: SeedModel = { owner: 'bob', name: 'mine', tasks: ['classification'], inputs: ['text'], version: 1 }
const RESULTS = { accuracy: 0.9123, precision: 0.8, recall: 0.7, f1: 0.75, auc: 0.95 }

/** The page of a model, on its Evaluation tab, with the evaluations the server holds. */
async function open(
  address: string,
  evaluations: Parameters<ReturnType<typeof stubBackend>['models']['addEvaluation']>[1][] = [],
  user: typeof bob | typeof ada = bob,
) {
  const backend = stubBackend(user, undefined, { models: [NER, MINE] })
  evaluations.forEach((e) => backend.models.addEvaluation(address, e))
  renderApp(`/models/${address}`)
  await userEvent.click(await screen.findByRole('tab', { name: 'Evaluation' }))
  return backend
}

it('says so when a model has not been evaluated', async () => {
  await open('lab/ner-fr-v1')
  expect(await screen.findByText('Not evaluated yet.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Start an evaluation/ })).not.toBeInTheDocument() // measured ones come later
})

it('lists the evaluations by task, with the metrics the platform defines and only the ones that were chosen', async () => {
  await open('lab/ner-fr-v1', [
    { task: 'classification', results: RESULTS, shown: ['accuracy', 'f1'], dataset: 'ada/reviews', split: 'test', version: 2 },
    { task: 'regression', results: { mae: 1.5, rmse: 2.25, r2: 0.4 }, shown: ['mae'] },
  ])
  const classification = (await screen.findByRole('heading', { level: 3, name: 'Classification' })).closest('div')!
  expect(within(classification).getByRole('columnheader', { name: 'Accuracy' })).toBeInTheDocument()
  expect(within(classification).getByRole('columnheader', { name: 'F1' })).toBeInTheDocument()
  expect(within(classification).queryByRole('columnheader', { name: 'Recall' })).not.toBeInTheDocument() // not chosen
  const row = within(classification).getByRole('link', { name: 'ada/reviews' }).closest('tr')!
  expect(within(row).getByText('0.912')).toBeInTheDocument() // three decimals, no more
  expect(within(row).getByText('0.75')).toBeInTheDocument()
  expect(within(row).getByText('test')).toBeInTheDocument()
  expect(within(row).getByText('+3 hidden')).toBeInTheDocument() // what a reader is told is not shown
  const regression = screen.getByRole('heading', { level: 3, name: 'Regression' }).closest('div')!
  expect(within(regression).getByRole('columnheader', { name: /MAE/ })).toHaveTextContent('MAE ↓') // lower is better
})

it('says that a result somebody sent was sent, and not measured', async () => {
  await open('lab/ner-fr-v1', [
    { task: 'classification', results: RESULTS, shown: ['accuracy'], source: 'submitted', created_by_username: 'ada' },
    { task: 'classification', results: RESULTS, shown: ['accuracy'], source: 'measured', created_by_username: 'bob' },
  ])
  const sent = await screen.findByText('Sent')
  expect(sent).toHaveAttribute('title', expect.stringContaining('the platform did not measure it'))
  expect(screen.getByText('Measured')).toHaveAttribute('title', expect.stringContaining('Measured by the platform'))
})

it('does not give the address of a dataset the person may not read', async () => {
  await open('lab/ner-fr-v1', [{ task: 'classification', results: RESULTS, shown: ['accuracy'], dataset: null, split: 'test' }])
  const row = (await screen.findByText('test')).closest('tr')!
  expect(within(row).queryByRole('link')).not.toBeInTheDocument()
  expect(within(row).getByTitle('No dataset, or one you may not read')).toHaveTextContent('—')
})

// ---- one evaluation

it('shows a reader only the metrics that were chosen, and says how many were left out', async () => {
  await open('lab/ner-fr-v1', [
    { task: 'classification', results: RESULTS, shown: ['accuracy', 'f1'], note: 'cross-validation', target_column: 'label', items: 1200, created_by_username: 'ada' },
  ])
  await userEvent.click(await screen.findByText('0.912'))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByText('Accuracy')).toBeInTheDocument()
  expect(within(dialog).queryByText('Recall')).not.toBeInTheDocument()
  expect(within(dialog).getByText('3 other metrics were computed but are not shown by ada.')).toBeInTheDocument()
  expect(within(dialog).getByText('cross-validation')).toBeInTheDocument()
  expect(within(dialog).getByText('Target column: label')).toBeInTheDocument()
  expect(within(dialog).getByText(/1200 items/)).toBeInTheDocument()
  expect(within(dialog).queryByRole('checkbox')).not.toBeInTheDocument() // a reader chooses nothing
  expect(within(dialog).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
})

it('shows the people who can edit the model every metric, and lets them choose which ones the others see', async () => {
  const backend = await open('bob/mine', [{ task: 'classification', results: RESULTS, shown: ['accuracy'] }], bob)
  await userEvent.click(await screen.findByText('0.912'))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getAllByRole('checkbox')).toHaveLength(5) // every metric, only one ticked
  expect(within(dialog).getByRole('checkbox', { name: 'Show Accuracy to the others' })).toBeChecked()
  expect(within(dialog).getByRole('checkbox', { name: 'Show Recall to the others' })).not.toBeChecked()
  await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Show Recall to the others' }))
  await waitFor(() => expect(within(dialog).getByRole('checkbox', { name: 'Show Recall to the others' })).toBeChecked())
  expect(backend.models.models[1].evaluations[0].shown).toEqual(['accuracy', 'recall'])
  // The table behind follows.
  expect(screen.getByRole('columnheader', { name: 'Recall', hidden: true })).toBeInTheDocument()
})

it('says what went wrong when the choice cannot be saved', async () => {
  const backend = await open('bob/mine', [{ task: 'classification', results: RESULTS, shown: ['accuracy'] }])
  backend.models.intercept = (url) => (url.endsWith('/shown') ? new Reply(500) : undefined)
  await userEvent.click(await screen.findByText('0.912'))
  const dialog = await screen.findByRole('dialog')
  await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Show Recall to the others' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Something went wrong')
  expect(backend.models.models[1].evaluations[0].shown).toEqual(['accuracy']) // nothing changed
})

it('deletes an evaluation after a second click', async () => {
  const backend = await open('bob/mine', [{ task: 'classification', results: RESULTS, shown: ['accuracy'] }])
  await userEvent.click(await screen.findByText('0.912'))
  const dialog = await screen.findByRole('dialog')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Delete' }))
  expect(backend.models.models[1].evaluations).toHaveLength(1) // one click is not enough
  await userEvent.click(within(dialog).getByRole('button', { name: 'Delete for good' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(await screen.findByText('Not evaluated yet.')).toBeInTheDocument()
  expect(backend.models.models[1].evaluations).toHaveLength(0)
})

it('tells an admin who can edit any model that every metric is theirs to choose', async () => {
  await open('lab/ner-fr-v1', [{ task: 'classification', results: RESULTS, shown: ['accuracy'] }], ada)
  await userEvent.click(await screen.findByText('0.912'))
  expect(within(await screen.findByRole('dialog')).getAllByRole('checkbox')).toHaveLength(5)
})

// ---- when it does not work

it('says what went wrong when the evaluations cannot be read', async () => {
  const backend = stubBackend(bob, undefined, { models: [NER] })
  backend.models.intercept = (url) => (url.endsWith('/evaluations') ? new Reply(500) : undefined)
  renderApp('/models/lab/ner-fr-v1')
  await userEvent.click(await screen.findByRole('tab', { name: 'Evaluation' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
})

it('keeps what people did with proposals, which is not an evaluation of the platform', async () => {
  await open('lab/ner-fr-v1')
  expect(await screen.findByText('Judged by annotators')).toBeInTheDocument()
})
