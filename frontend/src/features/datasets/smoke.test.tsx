import { render } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AnnotationRoute } from './annotation/AnnotationRoute'
import { getState } from './annotation/store'
import { DATASETS } from './mockData'
import { DatasetDetailPage } from './pages/DatasetDetailPage'
import { DatasetsPage } from './pages/DatasetsPage'

/** Every screen must at least draw: a crash on one of them leaves a blank page. */
function at(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/datasets" element={<DatasetsPage />} />
        <Route path="/datasets/:owner/:name" element={<DatasetDetailPage />} />
        <Route path="/datasets/:owner/:name/annotate/:projectId" element={<AnnotationRoute />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('datasets screens', () => {
  it('draws the list', () => {
    expect(at('/datasets').container.textContent).toContain('movie-reviews-fr')
  })

  it.each(DATASETS.map((d) => [d.owner + '/' + d.name]))('draws the page of %s', (key) => {
    expect(at(`/datasets/${key}`).container.textContent?.length).toBeGreaterThan(50)
  })

  it.each(getState().projects.map((p) => [p.id + ' ' + p.task, p.datasetKey, p.id]))('draws the workspace of %s', (_label, key, id) => {
    expect(at(`/datasets/${key}/annotate/${id}`).container.textContent?.length).toBeGreaterThan(50)
  })
})

describe('pre-annotation', () => {
  it('opens from the annotation tab, starts a run and shows its progress', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const { screen, within } = await import('@testing-library/react')
    const user = userEvent.setup()
    at('/datasets/mitchou/movie-reviews-fr')
    await user.click(await screen.findByRole('tab', { name: /annotation/i }))
    const buttons = await screen.findAllByRole('button', { name: /pré-annotation|pre-annotation/i })
    expect(buttons.length).toBeGreaterThan(0)
    await user.click(buttons[0])
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Quel modèle choisir|Which model to choose/i)).toBeTruthy()
    await user.click(within(dialog).getByRole('button', { name: /lancer|start/i }))
    expect((await within(dialog).findAllByText(/en cours|running/i)).length).toBeGreaterThan(0)
  })
})
