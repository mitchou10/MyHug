import { useSyncExternalStore } from 'react'
import type { ValueType } from './format'

/** Temporary in-memory store: replaced by the API once the backend handles annotations. */
/**
 * Text: classification, ner, qa. Tabular: label a row, review cells, describe the columns. Image: detection and
 * segmentation (polygons), classification, image to text. Audio: classification, labelled segments, transcription,
 * description. Video: classification, labelled segments, object tracking, description. Regression works for text,
 * tabular, audio and video. Time series: classification, labelled segments, description.
 */
export type TaskType = 'classification' | 'ner' | 'qa' | 'regression' | 'row_label' | 'cell_review' | 'column_schema'
  | 'image_detection' | 'image_segmentation' | 'image_polyline' | 'image_keypoints' | 'image_classification' | 'image_caption' | 'image_vqa'
  | 'audio_classification' | 'audio_segments' | 'audio_transcription' | 'audio_caption'
  | 'video_classification' | 'video_segments' | 'video_tracking' | 'video_caption'
  | 'timeseries_classification' | 'timeseries_segments' | 'timeseries_caption'
export const TEXT_TASKS: TaskType[] = ['classification', 'ner', 'qa', 'regression']
export const IMAGE_TASKS: TaskType[] = ['image_detection', 'image_segmentation', 'image_polyline', 'image_keypoints', 'image_classification', 'image_caption', 'image_vqa']
export const AUDIO_TASKS: TaskType[] = ['audio_classification', 'audio_segments', 'audio_transcription', 'audio_caption', 'regression']
export const VIDEO_TASKS: TaskType[] = ['video_classification', 'video_segments', 'video_tracking', 'video_caption', 'regression']
export const TIMESERIES_TASKS: TaskType[] = ['timeseries_classification', 'timeseries_segments', 'timeseries_caption', 'regression']
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
  /** Classification, image classification and row labelling: an item may get several labels. */
  multiLabel?: boolean
  /** Audio: annotate the whole clip (default) or stretches of it (`regions`). Segments and transcription always use regions. */
  granularity?: 'clip' | 'regions'
  /** Audio, with regions: the names of the tracks (lanes) the regions can be placed on. */
  tracks?: string[]
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

/** A point of a polygon, as a fraction of the width and of the height of the image (0 to 1): independent of the resolution. */
export type Pt = [number, number]
/** Detection and segmentation: one polygon with its label. */
export interface ImageObject { id: string; label: string; points: Pt[]; reason?: string }

/** Keypoints: one point of the skeleton (`label` = id of a label), and whether it is hidden behind something. */
export interface Keypoint { label: string; point: Pt; occluded?: boolean }
/** Keypoints: one instance (one person, one sign…) with the points placed so far. */
export interface KeypointInstance { id: string; points: Keypoint[] }

/** Audio: a stretch of the clip (in seconds) with a label (an event, a speaker) and/or what is said in it. */
export interface AudioSegment {
  id: string; start: number; end: number
  /** The lane (track) of the region, from 0. Overlapping regions live on different tracks. */
  track?: number
  /** `label` for a single label (segments), `labels` for several (classification), `text` for what is said or described, `value` for a score. */
  label?: string; labels?: string[]; text?: string; value?: number; reason?: string
}

/** Video tracking: where an object is at a moment (a box as fractions of the frame), or that it has left the frame. */
export interface Keyframe { t: number; box: [number, number, number, number]; outside?: boolean }
/** Video tracking: one object followed through the clip. Between two keyframes the box is interpolated. */
export interface ObjectTrack { id: string; label: string; keyframes: Keyframe[]; reason?: string }

/** Cell review: what is wrong with a cell (`issue` = id of a label), and what it should be. */
export interface CellNote { issue: string; corrected?: string; reason?: string }
/** Column schema: what a column is (`role` = id of a label), its type, formats, unit and description. */
export interface ColumnNote { role?: string; valueType?: ValueType; formats?: string[]; unit?: string; description?: string }

/** `label` is the id of a LabelDef; `reason` is the optional "why" of the annotator. */
/** Tasks where an item gets one or several labels from a list. */
export const supportsMultiLabel = (t: TaskType) => t === 'classification' || t === 'image_classification' || t === 'audio_classification' || t === 'video_classification' || t === 'timeseries_classification' || t === 'row_label'

export interface Answer { label?: string; labels?: string[]; reason?: string; spans?: Span[]; text?: string; qa?: QAPair[]
  /** Regression: the value given on the scale of the task. */
  value?: number
  /** Image: the polygons, and the sentences of an image to text task. */
  objects?: ImageObject[]
  captions?: string[]
  instances?: KeypointInstance[]
  /** Audio: the labelled or transcribed stretches of the clip. */
  segments?: AudioSegment[]
  /** Video: the objects followed through the clip. */
  tracks?: ObjectTrack[]
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
    {
      id: 'p11', datasetKey: 'mitchou/street-signs', name: 'Panneaux', task: 'image_detection', createdBy: 'mitchou', annotators: 3, done: 2400, total: 18400,
      labels: [
        { id: 'stop', name: 'stop', description: 'Panneau octogonal rouge « STOP ».' },
        { id: 'speed', name: 'limite de vitesse', description: 'Disque à bord rouge avec un nombre : entourer le disque seul, pas le poteau.' },
        { id: 'danger', name: 'danger', description: 'Triangle à bord rouge.' },
        { id: 'forbidden', name: 'interdiction', description: 'Autre panneau d’interdiction (sens interdit, stationnement…).' },
      ],
    },
    {
      id: 'p12', datasetKey: 'mitchou/street-signs', name: 'Route et abords', task: 'image_segmentation', createdBy: 'mitchou', annotators: 2, done: 640, total: 18400,
      labels: [
        { id: 'road', name: 'route', description: 'Chaussée et lignes peintes.' },
        { id: 'sidewalk', name: 'trottoir', description: 'Trottoirs et passages piétons surélevés.' },
        { id: 'building', name: 'bâtiment', description: 'Façades et murs.' },
        { id: 'vegetation', name: 'végétation', description: 'Arbres, haies, pelouse.' },
        { id: 'sky', name: 'ciel', description: 'Tout ce qui est au-dessus de l’horizon et n’est pas un objet.' },
      ],
    },
    {
      id: 'p13', datasetKey: 'mitchou/street-signs', name: 'Conditions de la scène', task: 'image_classification', multiLabel: true, createdBy: 'mitchou', annotators: 4, done: 9100, total: 18400,
      labels: [
        { id: 'sunny', name: 'ensoleillé', description: 'Ombres nettes, ciel dégagé.' },
        { id: 'rain', name: 'pluie', description: 'Pluie visible ou route mouillée.' },
        { id: 'night', name: 'nuit', description: 'Éclairage artificiel dominant.' },
        { id: 'fog', name: 'brouillard', description: 'Visibilité réduite.' },
      ],
    },
    { id: 'p14', datasetKey: 'mitchou/street-signs', name: 'Description de la scène', task: 'image_caption', labels: [], createdBy: 'mitchou', annotators: 2, done: 380, total: 18400 },
    {
      id: 'p15', datasetKey: 'mitchou/street-signs', name: 'Marquages au sol', task: 'image_polyline', createdBy: 'mitchou', annotators: 2, done: 210, total: 18400,
      labels: [
        { id: 'solid', name: 'ligne continue', description: 'Ligne blanche ou jaune sans interruption.' },
        { id: 'dashed', name: 'ligne discontinue', description: 'Une seule polyligne pour toute la ligne, pas un tracé par tiret.' },
        { id: 'edge', name: 'bord de chaussée', description: 'Limite entre la route et l’accotement.' },
      ],
    },
    {
      id: 'p16', datasetKey: 'mitchou/street-signs', name: 'Coins du panneau', task: 'image_keypoints', createdBy: 'mitchou', annotators: 2, done: 95, total: 18400,
      labels: [
        { id: 'tl', name: 'coin haut gauche', description: 'Angle supérieur gauche du panneau, sur le bord extérieur.' },
        { id: 'tr', name: 'coin haut droit', description: 'Angle supérieur droit du panneau.' },
        { id: 'br', name: 'coin bas droit', description: 'Angle inférieur droit du panneau.' },
        { id: 'bl', name: 'coin bas gauche', description: 'Angle inférieur gauche du panneau.' },
        { id: 'foot', name: 'pied du poteau', description: 'Point où le poteau touche le sol.' },
      ],
    },
    { id: 'p17', datasetKey: 'mitchou/street-signs', name: 'Questions sur la scène', task: 'image_vqa', labels: [], createdBy: 'mitchou', annotators: 3, done: 760, total: 18400 },
    {
      id: 'p18', datasetKey: 'mitchou/bird-sounds', name: 'Espèce', task: 'audio_classification', multiLabel: true, createdBy: 'mitchou', annotators: 3, done: 1900, total: 9600,
      labels: [
        { id: 'parus', name: 'mésange charbonnière', description: 'Chant en deux notes répétées, « tsi-tsi-pu ».' },
        { id: 'robin', name: 'rouge-gorge', description: 'Chant fluté, doux et varié.' },
        { id: 'blackbird', name: 'merle noir', description: 'Phrases longues et mélodieuses.' },
        { id: 'other', name: 'autre', description: 'Une espèce qui n’est pas dans la liste.' },
      ],
    },
    {
      id: 'p19', datasetKey: 'mitchou/bird-sounds', name: 'Chants et bruits', task: 'audio_segments', tracks: ['Piste 1'], createdBy: 'mitchou', annotators: 2, done: 430, total: 9600,
      labels: [
        { id: 'song', name: 'chant', description: 'Chant territorial ou de parade.' },
        { id: 'alarm', name: 'cri d’alarme', description: 'Cris courts et répétés.' },
        { id: 'noise', name: 'bruit parasite', description: 'Vent, voiture, voix humaine.' },
      ],
    },
    { id: 'p20', datasetKey: 'mitchou/bird-sounds', name: 'Qualité de l’enregistrement', task: 'regression', labels: [], scale: { min: 1, max: 5, step: 1, minLabel: 'Inutilisable', maxLabel: 'Excellent' }, createdBy: 'mitchou', annotators: 2, done: 700, total: 9600 },
    { id: 'p21', datasetKey: 'mitchou/bird-sounds', name: 'Description du son', task: 'audio_caption', labels: [], createdBy: 'mitchou', annotators: 1, done: 60, total: 9600 },
    { id: 'p22', datasetKey: 'lab/call-center-fr', name: 'Transcription horodatée', task: 'audio_transcription', tracks: ['Conseiller', 'Client'], labels: [], createdBy: 'mitchou', annotators: 4, done: 520, total: 3200 },
    {
      id: 'p23', datasetKey: 'lab/call-center-fr', name: 'Locuteurs', task: 'audio_segments', tracks: ['Voix', 'Fond sonore'], createdBy: 'mitchou', annotators: 2, done: 300, total: 3200,
      labels: [
        { id: 'agent', name: 'conseiller', description: 'La personne du service client.' },
        { id: 'customer', name: 'client', description: 'La personne qui appelle.' },
        { id: 'music', name: 'musique d’attente', description: 'Musique ou silence quand personne ne parle.' },
      ],
    },
    {
      id: 'p24', datasetKey: 'lab/call-center-fr', name: 'Ton de la conversation', task: 'audio_classification', granularity: 'regions', tracks: ['Conseiller', 'Client'], createdBy: 'mitchou', annotators: 2, done: 140, total: 3200,
      labels: [
        { id: 'calm', name: 'calme', description: 'Voix posée, ton neutre.' },
        { id: 'happy', name: 'satisfait', description: 'Ton chaleureux, remerciements.' },
        { id: 'angry', name: 'mécontent', description: 'Voix élevée, coupe la parole, reproches.' },
      ],
    },
    {
      id: 'p25', datasetKey: 'lab/kitchen-actions', name: 'Type de préparation', task: 'video_classification', multiLabel: true, createdBy: 'mitchou', annotators: 3, done: 900, total: 4200,
      labels: [
        { id: 'salad', name: 'salade', description: 'Légumes crus coupés et assaisonnés.' },
        { id: 'soup', name: 'soupe', description: 'Préparation cuite dans un liquide.' },
        { id: 'dessert', name: 'dessert', description: 'Préparation sucrée.' },
      ],
    },
    {
      id: 'p26', datasetKey: 'lab/kitchen-actions', name: 'Actions', task: 'video_segments', tracks: ['Main gauche', 'Main droite'], createdBy: 'mitchou', annotators: 2, done: 310, total: 4200,
      labels: [
        { id: 'cut', name: 'couper', description: 'Du premier contact de la lame jusqu’à la fin du geste.' },
        { id: 'mix', name: 'mélanger', description: 'Mouvement répété d’un ustensile dans un récipient.' },
        { id: 'pour', name: 'verser', description: 'Du début de l’inclinaison jusqu’à ce que le flux s’arrête.' },
        { id: 'peel', name: 'éplucher', description: 'Retirer la peau d’un légume ou d’un fruit.' },
      ],
    },
    {
      id: 'p27', datasetKey: 'lab/kitchen-actions', name: 'Suivi des ustensiles', task: 'video_tracking', createdBy: 'mitchou', annotators: 2, done: 120, total: 4200,
      labels: [
        { id: 'knife', name: 'couteau', description: 'Le couteau entier, manche compris.' },
        { id: 'spoon', name: 'cuillère', description: 'Cuillère ou louche.' },
        { id: 'bowl', name: 'bol', description: 'Bol, saladier ou casserole.' },
      ],
    },
    { id: 'p28', datasetKey: 'lab/kitchen-actions', name: 'Description de la recette', task: 'video_caption', granularity: 'regions', tracks: ['Étapes'], labels: [], createdBy: 'mitchou', annotators: 2, done: 75, total: 4200 },
    { id: 'p29', datasetKey: 'lab/kitchen-actions', name: 'Qualité de l’image', task: 'regression', labels: [], scale: { min: 1, max: 5, step: 1, minLabel: 'Inutilisable', maxLabel: 'Excellente' }, createdBy: 'mitchou', annotators: 2, done: 540, total: 4200 },
    {
      id: 'p30', datasetKey: 'lab/sales-timeseries', name: 'Profil de la série', task: 'timeseries_classification', multiLabel: true, createdBy: 'mitchou', annotators: 3, done: 180, total: 2500,
      labels: [
        { id: 'up', name: 'tendance haussière', description: 'Le niveau moyen monte sur l’ensemble de la période.' },
        { id: 'down', name: 'tendance baissière', description: 'Le niveau moyen baisse sur l’ensemble de la période.' },
        { id: 'season', name: 'saisonnalité', description: 'Un motif qui se répète à intervalle régulier.' },
        { id: 'shift', name: 'rupture de niveau', description: 'Le niveau change brutalement et ne revient pas.' },
      ],
    },
    {
      id: 'p31', datasetKey: 'lab/sales-timeseries', name: 'Événements', task: 'timeseries_segments', tracks: ['Piste 1'], createdBy: 'mitchou', annotators: 2, done: 95, total: 2500,
      labels: [
        { id: 'promo', name: 'promotion', description: 'Pic de ventes lié à une opération commerciale.' },
        { id: 'stockout', name: 'rupture de stock', description: 'Les ventes tombent presque à zéro sur quelques points.' },
        { id: 'holiday', name: 'jour férié', description: 'Creux ou pic expliqué par un jour férié.' },
        { id: 'anomaly', name: 'anomalie', description: 'Valeur inexpliquée : à vérifier.' },
      ],
    },
    { id: 'p32', datasetKey: 'lab/sales-timeseries', name: 'Résumé de la série', task: 'timeseries_caption', labels: [], createdBy: 'mitchou', annotators: 1, done: 30, total: 2500 },
    { id: 'p33', datasetKey: 'lab/sales-timeseries', name: 'Prévisibilité', task: 'regression', labels: [], scale: { min: 1, max: 5, step: 1, minLabel: 'Imprévisible', maxLabel: 'Très régulière' }, createdBy: 'mitchou', annotators: 2, done: 260, total: 2500 },
  ],
  answers: {},
}
const listeners = new Set<() => void>()
const set = (next: State) => { state = next; listeners.forEach((l) => l()) }

export const useAnnotations = () => useSyncExternalStore((cb) => (listeners.add(cb), () => void listeners.delete(cb)), () => state)

export function addProject(p: Omit<AnnotationProject, 'id' | 'annotators' | 'done'>) {
  set({ ...state, projects: [...state.projects, { ...p, id: `p${Date.now()}`, annotators: 0, done: 0 }] })
}
/** Changes any settings of a task (labels, scale, tracks…) in one go. */
export function patchProject(projectId: string, patch: Partial<AnnotationProject>) {
  set({ ...state, projects: state.projects.map((p) => (p.id === projectId ? { ...p, ...patch } : p)) })
}
/** Whether the annotator marks stretches of a clip (with tracks) rather than the whole clip. */
export const usesRegions = (p: AnnotationProject) => p.task === 'audio_segments' || p.task === 'audio_transcription' || p.task === 'video_segments' || p.task === 'timeseries_segments' || p.granularity === 'regions'
export const DEFAULT_TRACKS = ['Piste 1']
export function updateLabels(projectId: string, labels: LabelDef[]) {
  set({ ...state, projects: state.projects.map((p) => (p.id === projectId ? { ...p, labels } : p)) })
}
export function updateScale(projectId: string, scale: Scale) {
  set({ ...state, projects: state.projects.map((p) => (p.id === projectId ? { ...p, scale } : p)) })
}
/** The labels an item has, whether the task takes one or several. */
export const labelsOf = (a: Answer): string[] => a.labels ?? (a.label ? [a.label] : [])
/** Chooses a label: in single mode it replaces the previous one (and a second click clears it); in multi-label mode it is toggled. */
export function withLabel(a: Answer, id: string, multi?: boolean): Answer {
  const cur = labelsOf(a)
  if (!multi) return { ...a, label: cur.length === 1 && cur[0] === id ? undefined : id, labels: undefined }
  const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]
  return { ...a, label: undefined, labels: next.length ? next : undefined }
}
export function setMultiLabel(projectId: string, multiLabel: boolean) {
  set({ ...state, projects: state.projects.map((p) => (p.id === projectId ? { ...p, multiLabel } : p)) })
}
export function saveAnswer(projectId: string, row: number, answer: Answer) {
  set({ ...state, answers: { ...state.answers, [projectId]: { ...state.answers[projectId], [row]: answer } } })
}
