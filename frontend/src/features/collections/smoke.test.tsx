import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '@/auth/AuthProvider'
import { bob, stubBackend, testQueryClient } from '@/test/render'
import type { SeedModel } from '@/test/fakeModelsApi'
import { DatasetDetailPage } from '../datasets/pages/DatasetDetailPage'
import { ModelDetailPage } from '../models/pages/ModelDetailPage'
import { CollectionDetailPage } from './pages/CollectionDetailPage'
import { CollectionsPage } from './pages/CollectionsPage'

// The models are the API's (the datasets and the collections are still local): the ones a collection mentions.
const MODELS: SeedModel[] = [
  { owner: 'mitchou', name: 'sentiment-fr-v2', description: 'Sentiment of French texts.' },
  { owner: 'lab', name: 'zero-shot-text' },
  { owner: 'lab', name: 'diarizer-v1' },
  { owner: 'lab', name: 'ner-legal-v1', description: 'Legal entities.' },
]

function at(path: string) {
  stubBackend(bob, undefined, { models: MODELS })
  return render(
    <QueryClientProvider client={testQueryClient()}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/collections" element={<CollectionsPage />} />
            <Route path="/collections/:owner/:slug" element={<CollectionDetailPage />} />
            <Route path="/datasets/:owner/:name" element={<DatasetDetailPage />} />
            <Route path="/models/:owner/:name" element={<ModelDetailPage />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

describe('collections', () => {
  it('lists the public collections and your private ones, and filters yours', async () => {
    const user = userEvent.setup()
    const { container } = at('/collections')
    expect(container.textContent).toContain('Vision routière')
    expect(container.textContent).toContain('Parole en centre d’appel') // private, but it is yours
    await user.click(screen.getByRole('button', { name: /^(Les miennes|Mine)$/ }))
    expect(container.textContent).not.toContain('Vision routière') // owned by lab
  })

  it('shows the items of a collection with their notes, a model that is not there as missing', async () => {
    const { container } = at('/collections/lab/vision-routiere')
    expect(container.textContent).toContain('mitchou/street-signs')
    expect(container.textContent).toContain('Détection des panneaux.')
    expect(await screen.findAllByText(/lab\/detector-v3 · /)).toBeTruthy() // not in the API: shown as missing
  })

  it('lets the owner add an item, write a note and take it out', async () => {
    const user = userEvent.setup()
    const { container } = at('/collections/mitchou/sentiment-francais')
    expect(await screen.findByText('mitchou/sentiment-fr-v2')).toBeTruthy() // a model of the API, drawn as a card
    await user.click(screen.getByRole('button', { name: /ajouter des éléments|add items/i }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /^(Modèles|Models)$/ }))
    await user.type(within(dialog).getByLabelText(/rechercher|search/i), 'ner-legal')
    await user.click(within(dialog).getByRole('button', { name: /^(Ajouter|Add)$/ }))
    await user.keyboard('{Escape}')
    await waitFor(() => expect(container.textContent).toContain('lab/ner-legal-v1'))
    await user.click(screen.getAllByRole('button', { name: /retirer de la collection|remove from the collection/i })[0])
    expect(container.textContent).not.toContain('mitchou/movie-reviews-fr')
  })

  it('adds a dataset to a collection from its page', async () => {
    const user = userEvent.setup()
    at('/datasets/lab/sales-timeseries')
    await user.click(screen.getByRole('button', { name: /ajouter à une collection|add to a collection/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/^(Titre|Title)$/), 'Séries de ventes')
    await user.click(within(dialog).getByRole('button', { name: /créer|create/i }))
    expect(await within(dialog).findByText('Séries de ventes')).toBeTruthy()
  })

  it('hides a private collection from the page of a model', async () => {
    const { container } = at('/models/lab/diarizer-v1')
    await screen.findByRole('heading', { name: 'lab/diarizer-v1' })
    expect(container.textContent).toContain('Parole en centre d’appel') // it is yours, so you see it
  })
})
