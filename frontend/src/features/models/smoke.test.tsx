import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { MODEL_HUB } from './mockData'
import { ModelDetailPage } from './pages/ModelDetailPage'
import { ModelsPage } from './pages/ModelsPage'

/** Every screen must at least draw: a crash on one of them leaves a blank page. */
function at(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/models" element={<ModelsPage />} />
        <Route path="/models/:owner/:name" element={<ModelDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('models screens', () => {
  it('draws the list and filters it by kind of data', async () => {
    const user = userEvent.setup()
    const { container } = at('/models')
    expect(container.textContent).toContain('sentiment-fr-v2')
    await user.click(screen.getByRole('button', { name: /^(Image)$/ }))
    expect(container.textContent).toContain('detector-v3')
    expect(container.textContent).not.toContain('sentiment-fr-v2')
  })

  it('filters by what the model does, from a menu while no kind of data is chosen', async () => {
    const user = userEvent.setup()
    const { container } = at('/models')
    // Nothing but the menu: the tasks are not all on screen.
    expect(screen.queryByRole('button', { name: /Détection d'objets|Object detection/ })).toBeNull()
    await user.selectOptions(screen.getByRole('combobox', { name: /Fait|Does/ }), screen.getByRole('option', { name: /Détection d'objets|Object detection/ }))
    expect(container.textContent).toContain('detector-v3')
    expect(container.textContent).toContain('segmenter-sam-lite') // it detects too
    expect(container.textContent).not.toContain('pose-v1')
  })

  it('shows the few tasks of a kind of data as buttons, and drops a task that does not match the kind chosen', async () => {
    const user = userEvent.setup()
    const { container } = at('/models')
    await user.click(screen.getByRole('button', { name: /^(Image)$/ }))
    await user.click(screen.getByRole('button', { name: /Points clés|Keypoints/ }))
    expect(container.textContent).toContain('pose-v1')
    expect(container.textContent).not.toContain('detector-v3')
    await user.click(screen.getByRole('button', { name: /^(Texte|Text)$/ }))
    expect(container.textContent).toContain('sentiment-fr-v2') // the task was dropped with the kind of data
  })

  it.each(MODEL_HUB.map((m) => [m.id]))('draws the page of %s', (id) => {
    expect(at(`/models/${id}`).container.textContent?.length).toBeGreaterThan(100)
  })

  it('tries a model and shows its answer', async () => {
    const user = userEvent.setup()
    at('/models/mitchou/sentiment-fr-v2')
    await user.click(await screen.findByRole('tab', { name: /essayer|try/i }))
    await user.click(await screen.findByRole('button', { name: /lancer|run/i }))
    expect(await screen.findByText(/Résultat|Result/)).toBeTruthy()
  })

  it('declares a new model', async () => {
    const user = userEvent.setup()
    at('/models')
    await user.click(screen.getByRole('button', { name: /nouveau modèle|new model/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/^(Nom|Name)$/), 'my-model')
    await user.click(within(dialog).getByRole('button', { name: /créer|create/i }))
    expect(await screen.findByText('mitchou/my-model')).toBeTruthy()
  })
})
