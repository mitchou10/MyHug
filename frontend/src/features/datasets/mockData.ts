/** Temporary mock data: replaced by the API once the backend handles datasets. */
export type Modality = 'text' | 'image' | 'audio' | 'video' | 'tabular' | 'timeseries'

export interface Dataset {
  id: string
  owner: string
  name: string
  description: string
  modality: Modality
  language: string
  license: string
  tags: string[]
  rows: number
  sizeMb: number
  downloads: number
  likes: number
  updatedAt: string
  files: { path: string; sizeMb: number }[]
  columns: string[]
  sample: (string | number)[][]
  card: string
  /** Tabular only: what each column is supposed to contain. */
  schema?: { name: string; valueType: 'text' | 'date' | 'number' | 'identifier' | 'amount'; formats?: string[]; unit?: string }[]
  /** Time series only: the series to annotate (the sample above is a table, not a list of series). */
  collection?: { id: string; points: number; start: string }[]
  /** Time series only: points drawn by the viewer. */
  series?: { date: string; value: number }[]
}

const makeSeries = (n: number, base: number, amp: number) =>
  Array.from({ length: n }, (_, i) => {
    const d = new Date(Date.UTC(2023, 0, 1 + i * 7))
    return { date: d.toISOString().slice(0, 10), value: Math.round(base + amp * Math.sin(i / 5) + amp * 0.4 * Math.sin(i * 1.7) + i * 0.6) }
  })

export const DATASETS: Dataset[] = [
  {
    id: '1', owner: 'mitchou', name: 'movie-reviews-fr',
    description: 'Critiques de films en français annotées avec un sentiment (positif / négatif).',
    modality: 'text', language: 'fr', license: 'cc-by-4.0',
    tags: ['sentiment', 'cinéma', 'nlp'], rows: 120000, sizeMb: 84, downloads: 1280, likes: 42, updatedAt: '2026-11-10',
    files: [{ path: 'README.md', sizeMb: 0.01 }, { path: 'data/train.parquet', sizeMb: 68 }, { path: 'data/test.parquet', sizeMb: 16 }],
    columns: ['id', 'text', 'label'],
    sample: [
      [1, 'Un chef-d’œuvre, je recommande !', 'positive'], [2, 'Scénario faible et trop long.', 'negative'], [3, 'Belle photographie, rythme inégal.', 'positive'],
      [4, 'Je me suis ennuyé du début à la fin, les dialogues sonnent faux et le montage est confus.', 'negative'],
      [5, 'Une comédie fine et émouvante, portée par des acteurs au sommet de leur forme.', 'positive'],
      [6, 'Rien de neuf sous le soleil, un remake sans âme.', 'negative'],
      [7, 'La bande originale seule vaut le déplacement.', 'positive'],
      [8, 'Trop de clichés, mais quelques scènes sauvent le film.', 'negative'],
      [9, 'Une réalisation audacieuse qui mérite d’être vue en salle.', 'positive'],
      [10, 'Interminable. On regarde sa montre toutes les dix minutes.', 'negative'],
      [11, 'Touchant, drôle, parfaitement maîtrisé.', 'positive'],
      [12, 'Une fin décevante qui gâche une belle première heure.', 'negative'],
    ],
    card: 'Jeu de données de critiques de films collectées et annotées manuellement.\n\n## Usage\nTrain / test split fournis au format Parquet.',
  },
  {
    id: '2', owner: 'mitchou', name: 'street-signs',
    description: 'Photos de panneaux routiers avec boîtes englobantes pour la détection d’objets.',
    modality: 'image', language: 'multilingual', license: 'mit',
    tags: ['vision', 'routes', 'yolo'], rows: 18400, sizeMb: 2300, downloads: 640, likes: 18, updatedAt: '2026-10-28',
    files: [{ path: 'README.md', sizeMb: 0.01 }, { path: 'images.zip', sizeMb: 2250 }, { path: 'annotations.json', sizeMb: 50 }],
    columns: ['image', 'width', 'height', 'objects'],
    sample: [['img_0001.jpg', 1280, 720, 3], ['img_0002.jpg', 1280, 720, 1], ['img_0003.jpg', 1920, 1080, 5], ['img_0004.jpg', 1024, 768, 2], ['img_0005.jpg', 1280, 720, 4], ['img_0006.jpg', 1600, 900, 0]],
    card: 'Panneaux routiers européens annotés au format COCO.',
  },
  {
    id: '3', owner: 'lab', name: 'sales-timeseries',
    description: 'Ventes quotidiennes de 500 magasins sur 3 ans, pour la prévision de séries temporelles.',
    modality: 'timeseries', language: 'en', license: 'apache-2.0',
    tags: ['retail', 'forecast', 'tabular'], rows: 547500, sizeMb: 31, downloads: 3920, likes: 97, updatedAt: '2026-09-02',
    files: [{ path: 'README.md', sizeMb: 0.01 }, { path: 'sales.csv', sizeMb: 31 }],
    columns: ['date', 'store', 'item', 'sales'],
    sample: [['2023-01-01', 1, 'A12', 14], ['2023-01-02', 1, 'A12', 11], ['2023-01-03', 1, 'A12', 19]],
    card: 'Données synthétiques inspirées de cas réels de la grande distribution.',
    series: makeSeries(120, 40, 14),
    collection: [
      { id: 'store-01 · A12', points: 104, start: '2023-01-01' }, { id: 'store-01 · B07', points: 104, start: '2023-01-01' }, { id: 'store-02 · A12', points: 104, start: '2023-01-01' },
      { id: 'store-03 · C31', points: 104, start: '2023-01-01' }, { id: 'store-04 · A12', points: 104, start: '2023-01-01' },
    ],
  },
  {
    id: '4', owner: 'lab', name: 'qa-instructions',
    description: 'Paires question / réponse pour le fine-tuning d’assistants conversationnels.',
    modality: 'text', language: 'en', license: 'cc0-1.0',
    tags: ['llm', 'instruction', 'nlp'], rows: 52000, sizeMb: 210, downloads: 8100, likes: 230, updatedAt: '2026-11-18',
    files: [{ path: 'README.md', sizeMb: 0.01 }, { path: 'train.jsonl', sizeMb: 210 }],
    columns: ['question', 'answer', 'source'],
    sample: [
      ['Capital of France?', 'Paris', 'wiki'], ['2 + 2 ?', '4', 'synthetic'], ['Who wrote Hamlet?', 'Shakespeare', 'wiki'],
      ['What is the boiling point of water at sea level?', '100 °C (212 °F).', 'wiki'],
      ['Explain what a hash table is in one sentence.', 'A data structure that maps keys to values using a hash function to find a slot in an array.', 'synthetic'],
      ['Who painted the Mona Lisa?', 'Leonardo da Vinci', 'wiki'],
      ['How many bytes are in a kilobyte?', '1000 bytes in the SI definition, 1024 in the traditional binary one.', 'forum'],
      ['What is the derivative of x²?', '2x', 'synthetic'],
      ['Name the largest planet of the solar system.', 'Jupiter', 'wiki'],
      ['How do I undo my last git commit but keep the changes?', 'Run `git reset --soft HEAD~1`.', 'forum'],
    ],
    card: 'Instruction-following dataset, deduplicated and filtered.',
  },
  {
    id: '5', owner: 'mitchou', name: 'bird-sounds',
    description: 'Enregistrements audio de 120 espèces d’oiseaux avec étiquette d’espèce.',
    modality: 'audio', language: 'n/a', license: 'cc-by-nc-4.0',
    tags: ['audio', 'biodiversité'], rows: 9600, sizeMb: 5400, downloads: 310, likes: 11, updatedAt: '2026-08-14',
    files: [{ path: 'README.md', sizeMb: 0.01 }, { path: 'audio/', sizeMb: 5400 }],
    columns: ['file', 'species', 'duration_s'],
    sample: [['a001.wav', 'Parus major', 12.4], ['a002.wav', 'Erithacus rubecula', 8.1], ['a003.wav', 'Turdus merula', 15.9], ['a004.wav', 'Fringilla coelebs', 10.2], ['a005.wav', 'Sylvia atricapilla', 7.6], ['a006.wav', 'Parus major', 13.3]],
    card: 'Chants d’oiseaux collectés en Europe de l’Ouest.',
  },
  {
    id: '6', owner: 'lab', name: 'kitchen-actions',
    description: 'Clips vidéo courts de gestes en cuisine, annotés par action (couper, mélanger, verser…).',
    modality: 'video', language: 'n/a', license: 'cc-by-4.0',
    tags: ['vidéo', 'actions', 'egocentric'], rows: 4200, sizeMb: 18600, downloads: 520, likes: 27, updatedAt: '2026-11-02',
    files: [{ path: 'README.md', sizeMb: 0.01 }, { path: 'clips/', sizeMb: 18500 }, { path: 'labels.csv', sizeMb: 0.4 }],
    columns: ['clip', 'action', 'duration_s', 'fps'],
    sample: [['clip_0001.mp4', 'couper', 6.2, 25], ['clip_0002.mp4', 'mélanger', 9.8, 25], ['clip_0003.mp4', 'verser', 4.5, 25], ['clip_0004.mp4', 'éplucher', 12.1, 25], ['clip_0005.mp4', 'couper', 8.4, 25], ['clip_0006.mp4', 'mélanger', 11.0, 25]],
    card: 'Clips à la première personne filmés dans 40 cuisines.',
  },
  {
    id: '7', owner: 'mitchou', name: 'house-prices',
    description: 'Annonces immobilières avec surface, nombre de pièces, ville et prix de vente.',
    modality: 'tabular', language: 'fr', license: 'odbl',
    tags: ['immobilier', 'régression'], rows: 85000, sizeMb: 12, downloads: 2210, likes: 64, updatedAt: '2026-10-05',
    files: [{ path: 'README.md', sizeMb: 0.01 }, { path: 'houses.csv', sizeMb: 12 }],
    columns: ['id', 'surface_m2', 'rooms', 'city', 'price_eur'],
    schema: [
      { name: 'id', valueType: 'identifier', formats: ['D+'] },
      { name: 'surface_m2', valueType: 'number', formats: ['D+'], unit: 'm²' },
      { name: 'rooms', valueType: 'number', formats: ['D+'] },
      { name: 'city', valueType: 'text' },
      { name: 'price_eur', valueType: 'amount', formats: ['D+'], unit: '€' },
    ],
    sample: [
      [1, 54, 3, 'Lyon', 262000], [2, 82, 4, 'Paris', 710000], [3, 38, 2, 'Lille', 158000], [4, 120, 6, 'Nantes', 489000],
      [5, 67, 3, 'Lyon', 331000], [6, 95, 5, 'Bordeaux', 402000], [7, 5, 3, 'Paris', 890000], [8, 74, 0, 'lyon ', 298000],
      [9, 54, 3, 'Lyon', 262000], [10, 61, 3, 'Toulouse', ''], [11, 210, 9, 'Nice', 1250000], [12, 48, 2, 'Rennes', 'n/a'],
      [13, 88, 4, 'Marseille', -310000], [14, 102, 5, 'Strasbourg', 365000],
    ],
    card: 'Transactions anonymisées issues de données publiques.',
  },
  {
    id: '8', owner: 'lab', name: 'decisions-justice',
    description: 'Extraits de décisions de justice pénale anonymisées, à annoter (personnes, dates, infractions, peines).',
    modality: 'text', language: 'fr', license: 'etalab-2.0',
    tags: ['juridique', 'ner', 'droit pénal'], rows: 14500, sizeMb: 46, downloads: 740, likes: 33, updatedAt: '2026-11-20',
    files: [{ path: 'README.md', sizeMb: 0.01 }, { path: 'decisions.jsonl', sizeMb: 46 }],
    columns: ['id', 'text', 'juridiction'],
    sample: [
      [1, 'Le 12 mars 2023, Jean Dupont a été interpellé à Lyon pour conduite sans permis et refus d’obtempérer.', 'Tribunal correctionnel'],
      [2, 'Marie Lefèvre a reconnu avoir volé un véhicule en bande organisée le 4 juin 2022 à Marseille.', 'Tribunal correctionnel'],
      [3, 'Le prévenu est condamné à huit mois d’emprisonnement avec sursis pour violences volontaires en récidive.', 'Cour d’appel'],
      [4, 'Karim Benali a menacé de mort son voisin avec une arme le 21 janvier 2024 à Lille.', 'Tribunal correctionnel'],
      [5, 'La cour relaxe Sophie Martin du chef d’abus de confiance, faute d’éléments intentionnels.', 'Cour d’appel'],
      [6, 'Il est reproché à Paul Girard d’avoir détourné 18 000 euros au préjudice de son employeur entre 2019 et 2021.', 'Tribunal correctionnel'],
      [7, 'Le tribunal prononce une amende de 3 000 euros et la suspension du permis de conduire pendant six mois.', 'Tribunal de police'],
      [8, 'Lors de l’audience du 9 septembre 2023 à Bordeaux, Lucie Moreau a contesté les faits de harcèlement moral (affaire n° 2301457).', 'Conseil de prud’hommes'],
    ],
    card: 'Décisions anonymisées de plusieurs juridictions françaises, destinées à l’extraction d’informations juridiques.',
  },
  {
    id: '9', owner: 'lab', name: 'call-center-fr',
    description: 'Appels de service client en français, à transcrire et à découper par locuteur.',
    modality: 'audio', language: 'fr', license: 'cc-by-nc-4.0',
    tags: ['parole', 'asr', 'diarisation'], rows: 3200, sizeMb: 2100, downloads: 410, likes: 22, updatedAt: '2026-11-12',
    files: [{ path: 'README.md', sizeMb: 0.01 }, { path: 'calls/', sizeMb: 2100 }, { path: 'metadata.csv', sizeMb: 0.3 }],
    columns: ['file', 'topic', 'duration_s'],
    sample: [['call_001.wav', 'facturation', 18.5], ['call_002.wav', 'résiliation', 14.2], ['call_003.wav', 'panne', 19.8], ['call_004.wav', 'renseignement', 9.4], ['call_005.wav', 'facturation', 16.1]],
    card: 'Appels anonymisés, 8 kHz, deux locuteurs en moyenne.',
  },
]

export const MODALITIES: Modality[] = ['text', 'image', 'audio', 'video', 'tabular', 'timeseries']

export const getDataset = (owner?: string, name?: string) => DATASETS.find((d) => d.owner === owner && d.name === name)
