import { useSyncExternalStore } from 'react'
import type { ValueType } from './format'

/** Temporary in-memory store: replaced by the API once the backend handles annotations. */
/** Text: classification, ner, qa. Tabular: label a row, review cells, describe the columns. */
export type TaskType = 'classification' | 'ner' | 'qa' | 'regression' | 'row_label' | 'cell_review' | 'column_schema'
export const TEXT_TASKS: TaskType[] = ['classification', 'ner', 'qa', 'regression']
export const TABULAR_TASKS: TaskType[] = ['row_label', 'cell_review', 'column_schema', 'regression']

/** NER only. `entity`: a small unit (a name, a date…). `semantic`: a business meaning, often a longer passage (an offence, a sentence…). */
export type LabelKind = 'entity' | 'semantic'
export interface LabelDef { id: string; name: string; description: string; kind?: LabelKind
  /** NER: the type of the extracted value, its expected format (see format.ts) and examples shown to annotators. */
  valueType?: ValueType
  formats?: string[]
  examples?: string[]
}

/** Mocked current user: only the creator of a task can edit its labels. */
export const CURRENT_USER = 'mitchou'
export const newLabel = (): LabelDef => ({ id: Math.random().toString(36).slice(2, 8), name: '', description: '', kind: 'entity', valueType: 'text', formats: [], examples: [] })

/** Regression: the numeric value an annotator gives to each text or row, on a scale. */
export interface Scale { min: number; max: number; step: number; unit?: string; minLabel?: string; maxLabel?: string }

export interface AnnotationProject {
  id: string
  datasetKey: string // owner/name
  name: string
  task: TaskType
  labels: LabelDef[]
  /** Regression only. */
  scale?: Scale
  createdBy: string
  annotators: number
  /** Mocked progress of everybody else, on the whole dataset. */
  done: number
  total: number
}

export interface Span { start: number; end: number; label: string; reason?: string; value?: string } // label = id of a LabelDef // token indexes, end included
/** Question answering: several pairs per text. `sources` are the passages of the text that support the answer. */
export interface QAPair {
  id: string
  question: string
  answer: string
  /** Set when the answer was selected in the text (token indexes, end included). */
  answerSpan?: { start: number; end: number }
  sources: { start: number; end: number }[]
}
export const newPair = (): QAPair => ({ id: Math.random().toString(36).slice(2, 8), question: '', answer: '', sources: [] })

/** Cell review: what is wrong with a cell (`issue` = id of a label), and what it should be. */
export interface CellNote { issue: string; corrected?: string; reason?: string }
/** Column schema: what a column is (`role` = id of a label), its type, formats, unit and description. */
export interface ColumnNote { role?: string; valueType?: ValueType; formats?: string[]; unit?: string; description?: string }

/** `label` is the id of a LabelDef; `reason` is the optional "why" of the annotator. */
export interface Answer { label?: string; reason?: string; spans?: Span[]; text?: string; qa?: QAPair[]
  /** Regression: the value given on the scale of the task. */
  value?: number
  /** Tabular: notes by column index. A column schema is stored at row 0. */
  cells?: Record<number, CellNote>
  columns?: Record<number, ColumnNote>
}

interface State { projects: AnnotationProject[]; answers: Record<string, Record<number, Answer>> }

let state: State = {
  projects: [
    { id: 'p1', datasetKey: 'mitchou/movie-reviews-fr', name: 'Sentiment', task: 'classification', labels: [
      { id: 'positive', name: 'positive', description: 'L’auteur a aimé le film, même avec des réserves mineures.' },
      { id: 'negative', name: 'negative', description: 'L’auteur n’a pas aimé le film, ou le déconseille.' },
      { id: 'neutral', name: 'neutral', description: 'Avis mitigé ou purement factuel, sans prise de position.' },
    ], createdBy: 'mitchou', annotators: 4, done: 38200, total: 120000 },
    { id: 'p2', datasetKey: 'mitchou/movie-reviews-fr', name: 'Acteurs, films et lieux', task: 'ner', labels: [
      { id: 'PERSONNE', name: 'PERSONNE', kind: 'entity', description: 'Acteur, réalisateur, personnage cité.' },
      { id: 'FILM', name: 'FILM', kind: 'entity', description: 'Titre d’une œuvre.' },
      { id: 'LIEU', name: 'LIEU', kind: 'entity', description: 'Ville, pays, salle de cinéma.' },
    ], createdBy: 'lab', annotators: 2, done: 1450, total: 120000 },
    { id: 'p3', datasetKey: 'lab/qa-instructions', name: 'Qualité des réponses', task: 'classification', labels: [
      { id: 'good', name: 'good', description: 'La réponse est correcte, claire et complète.' },
      { id: 'bad', name: 'bad', description: 'La réponse est fausse, hors sujet ou incomplète.' },
    ], createdBy: 'lab', annotators: 6, done: 52000, total: 52000 },
    {
      id: 'p4', datasetKey: 'lab/decisions-justice', name: 'Infractions et peines', task: 'ner', createdBy: 'mitchou', annotators: 3, done: 620, total: 14500,
      labels: [
        { id: 'NOM', name: 'NOM', kind: 'entity', valueType: 'text', examples: ['Dupont', 'Martin'], description: 'Nom de famille d’une personne physique.' },
        { id: 'PRENOM', name: 'PRÉNOM', kind: 'entity', valueType: 'text', examples: ['Jean', 'Marie'], description: 'Prénom d’une personne physique.' },
        { id: 'DATE', name: 'DATE', kind: 'entity', valueType: 'date', formats: ['YYYY-MM-DD', 'DD/MM/YYYY'], examples: ['12 mars 2023 → 2023-03-12', '4 juin 2022 → 2022-06-04'], description: 'Date des faits ou de l’audience.' },
        { id: 'AFFAIRE', name: 'N° AFFAIRE', kind: 'entity', valueType: 'identifier', formats: ['DDDDDDD', 'DDDD/DDD'], examples: ['2301457', '2301/457'], description: 'Numéro de l’affaire : 7 chiffres, ou 4 + 3 chiffres séparés par une barre oblique.' },
        { id: 'MONTANT', name: 'MONTANT', kind: 'entity', valueType: 'amount', formats: ['D+.DD'], examples: ['18 000 euros → 18000.00', '3 000 euros → 3000.00'], description: 'Somme d’argent, en euros, normalisée avec 2 décimales.' },
        { id: 'LIEU', name: 'LIEU', kind: 'entity', valueType: 'text', examples: ['Lyon', 'Cour d’appel de Paris'], description: 'Ville, adresse ou juridiction.' },
        { id: 'INFRACTION', name: 'INFRACTION', kind: 'semantic', description: 'Faits qualifiés pénalement (vol, violences, abus de confiance…), avec leurs circonstances si elles font partie de l’infraction.' },
        { id: 'PEINE', name: 'PEINE', kind: 'semantic', description: 'Sanction prononcée : prison, sursis, amende, suspension…' },
        { id: 'DECISION', name: 'DÉCISION', kind: 'semantic', description: 'Issue de l’affaire : condamnation, relaxe, renvoi.' },
      ],
    },
    { id: 'p5', datasetKey: 'lab/decisions-justice', name: 'Questions sur les décisions', task: 'qa', labels: [], createdBy: 'mitchou', annotators: 2, done: 410, total: 14500 },
    {
      id: 'p6', datasetKey: 'mitchou/house-prices', name: 'Qualité des annonces', task: 'row_label', createdBy: 'mitchou', annotators: 3, done: 9200, total: 85000,
      labels: [
        { id: 'ok', name: 'normale', description: 'L’annonce est cohérente et exploitable telle quelle.' },
        { id: 'suspect', name: 'suspecte', description: 'Au moins une valeur paraît improbable (surface minuscule, prix hors marché…).' },
        { id: 'dup', name: 'doublon', description: 'Même bien que dans une autre ligne.' },
      ],
    },
    {
      id: 'p7', datasetKey: 'mitchou/house-prices', name: 'Valeurs à corriger', task: 'cell_review', createdBy: 'mitchou', annotators: 2, done: 310, total: 85000,
      labels: [
        { id: 'wrong', name: 'erreur', description: 'La valeur est fausse ou impossible (surface de 5 m², prix négatif).' },
        { id: 'missing', name: 'manquante', description: 'Cellule vide ou « n/a » : la valeur n’a pas été renseignée.' },
        { id: 'outlier', name: 'aberrante', description: 'Valeur possible mais très éloignée des autres (à vérifier).' },
        { id: 'format', name: 'format', description: 'La valeur est juste mais mal écrite (espaces, casse, unité).' },
      ],
    },
    {
      id: 'p8', datasetKey: 'mitchou/house-prices', name: 'Schéma des colonnes', task: 'column_schema', createdBy: 'mitchou', annotators: 1, done: 2, total: 5,
      labels: [
        { id: 'identifier', name: 'identifiant', description: 'Identifie une ligne de façon unique.' },
        { id: 'measure', name: 'mesure', description: 'Une quantité numérique (surface, nombre de pièces).' },
        { id: 'category', name: 'catégorie', description: 'Un nombre limité de valeurs possibles (ville, type).' },
        { id: 'date', name: 'date', description: 'Une date ou une heure.' },
        { id: 'target', name: 'cible', description: 'La valeur que l’on voudra prédire (prix).' },
      ],
    },
    { id: 'p9', datasetKey: 'mitchou/movie-reviews-fr', name: 'Note du film', task: 'regression', labels: [], scale: { min: 0, max: 10, step: 0.5, minLabel: 'Détestable', maxLabel: 'Chef-d’œuvre' }, createdBy: 'mitchou', annotators: 3, done: 5200, total: 120000 },
    { id: 'p10', datasetKey: 'mitchou/house-prices', name: 'Prix au m² estimé', task: 'regression', labels: [], scale: { min: 500, max: 15000, step: 50, unit: '€/m²', minLabel: 'Très bas', maxLabel: 'Très élevé' }, createdBy: 'mitchou', annotators: 2, done: 120, total: 85000 },
  ],
  answers: {},
}
const listeners = new Set<() => void>()
const set = (next: State) => { state = next; listeners.forEach((l) => l()) }

export const useAnnotations = () => useSyncExternalStore((cb) => (listeners.add(cb), () => void listeners.delete(cb)), () => state)

export function addProject(p: Omit<AnnotationProject, 'id' | 'annotators' | 'done'>) {
  set({ ...state, projects: [...state.projects, { ...p, id: `p${Date.now()}`, annotators: 0, done: 0 }] })
}
export function updateLabels(projectId: string, labels: LabelDef[]) {
  set({ ...state, projects: state.projects.map((p) => (p.id === projectId ? { ...p, labels } : p)) })
}
export function updateScale(projectId: string, scale: Scale) {
  set({ ...state, projects: state.projects.map((p) => (p.id === projectId ? { ...p, scale } : p)) })
}
export function saveAnswer(projectId: string, row: number, answer: Answer) {
  set({ ...state, answers: { ...state.answers, [projectId]: { ...state.answers[projectId], [row]: answer } } })
}
