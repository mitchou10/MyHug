# Backend du son, de la vidéo et des séries temporelles

Complète [backend-datasets.md](backend-datasets.md) (datasets, tâches, texte), [backend-tabular-annotation.md](backend-tabular-annotation.md)
(tableaux, régression) et [image-annotation-ideas.md](image-annotation-ideas.md) (images). Les conventions du premier
document s'appliquent sans changement (couches, `Actor`, UUID, Alembic, pas de table `users`, `annotation_labels` avec
`id` stable et suppression logique).

Le **son**, la **vidéo** et les **séries temporelles** sont traités ensemble parce que le frontend les sert avec le
même espace de travail (`TimedWorkspace.tsx`): une timeline, des **régions** placées sur des **pistes**, et une réponse
par région ou pour tout l'élément. Seuls changent la source (un fichier audio, un fichier vidéo, une série) et ce que
l'on affiche sur la timeline.

## 1. Ce que le frontend fait aujourd'hui

| Modalité | Tâches | Fichiers du frontend |
|---|---|---|
| Son | `audio_classification`, `audio_segments`, `audio_transcription`, `audio_caption`, `regression` | `AudioWorkspace.tsx`, `audioMock.ts`, `useAudioPlayer.ts` |
| Vidéo | `video_classification`, `video_segments`, `video_caption`, `regression`, et `video_tracking` (outil à part) | `VideoWorkspace.tsx`, `TrackingWorkspace.tsx`, `useClockPlayer.ts`, `videoMock.ts` |
| Série | `timeseries_classification`, `timeseries_segments`, `timeseries_caption`, `regression` | `TimeSeriesWorkspace.tsx`, `seriesMock.ts` |

Partagés: `TimedWorkspace.tsx`, `Waveform.tsx` (la timeline, avec la forme d'onde ou la courbe), `store.ts`
(`AudioSegment`, `ObjectTrack`, `Keyframe`).

**Deux niveaux de réponse** pour classification, description et régression, choisis à la création de la tâche:
- `granularity: 'clip'` (défaut): une réponse pour tout l'élément (`label`/`labels`, `captions`, `value`, `reason`).
- `granularity: 'regions'`: des régions `{ start, end, track, label, labels, text, value, reason }`. Les segments
  étiquetés et la transcription utilisent toujours des régions.

**Pistes** (`project.tracks`): une liste de noms. Chaque région a un indice de piste; deux régions de pistes différentes
peuvent se chevaucher.

## 2. Modèle de données

### 2.1 Configuration des tâches

`annotation_tasks.type` reçoit les valeurs

```
audio_classification | audio_segments | audio_transcription | audio_caption
video_classification | video_segments | video_tracking | video_caption
timeseries_classification | timeseries_segments | timeseries_caption
```

(`regression` existe déjà). Le préfixe n'est pas stocké à part: il se déduit du type de la tâche et doit **correspondre à
la modalité du dataset** (le service refuse `video_segments` sur un dataset audio).

Dans `annotation_tasks.config` (JSONB, validé par un modèle Pydantic par type, voir le document tabulaire):

| Clé | Types concernés | Sens |
|---|---|---|
| `granularity` | classification, description, régression | `clip` ou `regions` |
| `tracks` | toute tâche à régions | liste de noms, au moins 1, au plus ~16 |
| `multi_label` | classifications | plusieurs labels par élément ou par région |
| `scale` | régression | `{ min, max, step, unit, min_label, max_label }` |

Modifier `tracks` en cours de route est permis. **Supprimer une piste** ne supprime pas ses régions: elles passent sur
la piste 0 (le frontend borne déjà l'indice à `len(tracks) - 1`).

### 2.2 Les unités de temps

Les régions sont exprimées dans l'unité de la modalité:

| Modalité | Unité de `start` / `end` | Remarque |
|---|---|---|
| Son, vidéo | secondes depuis le début du fichier (`NUMERIC(12,4)`) | précision au dixième de milliseconde |
| Série | **horodatage** (`timestamptz`) en base, **indice de point** dans l'API du frontend | le frontend manipule des indices; le serveur convertit |

La conversion indice ↔ horodatage s'appuie sur la série (`start` et fréquence, voir **2.6**). Pour une série à pas
irrégulier, l'indice est la position dans la série triée.

### 2.3 Les régions

**`annotation_regions`**
- `id`, `annotation_id`, `position` (ordre d'affichage), `start`, `end` (`start < end`, bornés par la durée de l'élément),
  `track` (entier ≥ 0), `text`, `value` (`NUMERIC`), `reason`.
- Index sur `(annotation_id, start)`. Aucune contrainte d'exclusion: les chevauchements sont permis, même sur une
  même piste (le frontend ne les empêche pas). Le service peut renvoyer un **avertissement** pour un chevauchement
  sur une même piste, jamais une erreur.
- Durée minimale: 0,05 s pour un son ou une vidéo, 1 point pour une série.

**`annotation_region_labels`**: `(region_id, label_id)`, unique. Une région en a un (segments, transcription avec
locuteur) ou plusieurs (classification multi-label).

Pourquoi une table de jointure: le frontend a `label` (un seul) et `labels` (plusieurs) sur la même structure; côté
serveur, un seul modèle suffit. Le serveur reconstruit `label` / `labels` selon la tâche.

Réponses au niveau de l'élément entier (`granularity = clip`): elles réutilisent les tables du premier document
(`annotations.label_id` ou `annotation_choices`, `annotations.value`, `annotations.reason`) et une table de textes
partagée avec les images:

**`annotation_captions`**: `(annotation_id, position, text)`.

### 2.4 Le suivi d'objets (`video_tracking`)

**`annotation_tracks`**: `id`, `annotation_id`, `label_id`, `reason`.

**`track_keyframes`**: `id`, `track_id`, `t` (secondes, `NUMERIC(12,4)`), `x1`, `y1`, `x2`, `y2` (`REAL`, fractions de la
largeur et de la hauteur du cadre, entre 0 et 1), `outside` (bool). Unique `(track_id, t)`.

Règles d'interprétation, **identiques à celles du frontend** (`boxAt` dans `TrackingWorkspace.tsx`) et à reproduire
côté serveur pour les exports:
1. Avant la première image clé, l'objet n'existe pas.
2. Entre deux images clés visibles, la boîte est **interpolée linéairement**.
3. Après la dernière image clé visible, la boîte est **maintenue** jusqu'à la fin de la vidéo.
4. Une image clé `outside = true` marque la sortie du cadre: l'objet est caché à partir de là, jusqu'à la prochaine image
   clé visible. Entre une clé visible et une clé `outside`, la boîte est maintenue sans interpolation.

Un module `app/services/tracking.py` implémente `box_at(track, t)` et ses **tests partagés avec le frontend** (mêmes
vecteurs de test: clé unique, deux clés, sortie, reprise).

La boîte est le seul format de forme pour l'instant. Pour suivre des polygones, voir **6**.

### 2.5 Les fichiers son et vidéo

À ajouter à `dataset_files` (ou à une table `media_files`, une ligne par fichier lisible):
- Son: `duration_s`, `sample_rate`, `channels`, `codec`.
- Vidéo: `duration_s`, `fps` (valeur ou `NULL` si variable), `width`, `height`, `codec`.
- `peaks_key` (son): clé d'un fichier de **pics** précalculés (voir **4**).
- `proxy_key` (vidéo): clé d'une version légère pour l'annotation (voir **4**).

Le frontend suppose aujourd'hui **25 images par seconde** pour la vidéo et arrondit le temps à 1/25 s. Avec des vraies
vidéos, le serveur renvoie le `fps` réel, et l'API garde le temps en **secondes** (pas en numéro d'image) pour rester
valable si la fréquence change entre le fichier d'origine et son proxy. Un numéro d'image se déduit de `round(t × fps)`.

### 2.6 Les séries temporelles

Un dataset de séries est un ensemble de séries, pas un tableau de lignes.

**`dataset_series`**: `id`, `version_id`, `key` (le nom affiché: « store-01 · A12 »), `points`, `start` (`timestamptz`),
`end`, `freq` (texte ISO 8601, ex. `P7D`, ou `NULL` si irrégulier), `value_columns` (colonnes de valeurs), `storage_key`.

Les valeurs vivent dans un fichier Parquet, jamais dans la base. Les annotations pointent vers la série par
`dataset_series.id` (à la place de `split` et `row_index`). Dans `annotations`, `row_ref` accepte donc une clé de série.

Une série **multivariée** (plusieurs colonnes) est possible dans le modèle (`value_columns`); le frontend n'en affiche
qu'une.

## 3. API (ajouts)

Les routes de tâches, de lignes et d'annotations du premier document gardent leur forme. Ajouts:

**Éléments à annoter** — `GET /tasks/{id}/rows` renvoie, selon la modalité:
- Son: `{ id, duration_s, media_url, peaks_url, my_annotation }`.
- Vidéo: `{ id, duration_s, fps, width, height, media_url, thumbnails_url, my_annotation }`.
- Série: `{ id, key, points, start, freq, my_annotation }`, **sans les valeurs**.

**Médias** (son et vidéo): URL présignée qui accepte les **requêtes `Range`** (indispensables pour déplacer le curseur
sans tout télécharger). Les URL durent quelques minutes et sont renouvelées par `GET /tasks/{id}/rows/{ref}/media`.

**Pics** — `GET …/peaks?resolution=` renvoie un tableau de valeurs entre 0 et 1, avec plusieurs niveaux de détail pour
zoomer (voir **4**).

**Séries** — `GET /datasets/{owner}/{name}/series/{id}?from=&to=&max_points=` renvoie les points d'une fenêtre,
**sous-échantillonnés à `max_points`** (algorithme LTTB, qui conserve la forme de la courbe) quand la fenêtre est
trop grande. Le frontend demande la fenêtre visible à chaque zoom.

**Annotation** — `PUT /tasks/{id}/rows/{ref}/annotation`, idempotent, corps selon la tâche:

```jsonc
// classification, description, régression, au niveau de l'élément
{ "labels": ["…"], "reason": "…" }
{ "captions": ["…"] }
{ "value": 4, "reason": "…" }

// avec des régions (segments, transcription, ou granularity = regions)
{ "regions": [
    { "start": 3.2, "end": 7.8, "track": 1, "label_ids": ["…"], "text": "…", "value": null, "reason": null }
] }

// suivi d'objets
{ "tracks": [
    { "label_id": "…", "reason": null,
      "keyframes": [ { "t": 0.0, "box": [0.2, 0.3, 0.4, 0.6], "outside": false },
                     { "t": 4.0, "box": [0.5, 0.3, 0.7, 0.6], "outside": false },
                     { "t": 6.0, "box": [0.5, 0.3, 0.7, 0.6], "outside": true } ] }
] }
```

Le serveur **remplace** l'ensemble des régions (ou des pistes d'objets) de l'annotation de l'utilisateur. Il valide:
- `0 ≤ start < end ≤ durée` (pour une série, indices dans `[0, points − 1]`, convertis en horodatages);
- `track < len(config.tracks)`;
- pour les clés: `0 ≤ x1 < x2 ≤ 1`, `0 ≤ y1 < y2 ≤ 1`, `t` dans la durée, au moins une clé visible par piste;
- une région sans contenu utile (classification sans label, transcription sans texte ni locuteur, régression sans valeur)
  est ignorée, comme le fait le frontend à la validation.

**Enregistrement automatique.** Ces tâches enregistrent « en bloc » à la validation, pas à chaque geste. Mais un clip de
dix minutes avec des centaines de régions fait un corps de requête volumineux: prévoir une **limite** (par exemple
2 000 régions, 5 000 images clés) et un `PATCH` de **brouillon** pour les longues sessions (pas de perte si le navigateur
se ferme).

## 4. Préparer les médias (traitement à la création de la version)

Une tâche de fond (file de travail) qui, à la création d'une version, produit pour chaque fichier:

**Son**
- **Pics de forme d'onde** à plusieurs résolutions (ex. 500, 5 000 et 50 000 points), en JSON compact ou binaire
  (`.peaks`), générés par `ffmpeg` (ou `audiowaveform`). Sans cela, le navigateur devrait décoder le fichier entier.
- Un fichier lisible partout (AAC/Opus) si l'original est exotique.

**Vidéo**
- Un **proxy** de basse résolution (ex. 480p, GOP court) pour que le déplacement image par image soit fluide.
  L'annotation se fait sur le proxy; les coordonnées normalisées restent valables sur l'original.
- Des **vignettes** à intervalle régulier (une toutes les 1 à 5 s) et un sprite pour la prévisualisation.
- Les métadonnées: `fps`, durée, dimensions, rotation.

**Série**
- Un **résumé multi-échelles** (min, max, moyenne par fenêtre) pour tracer une série de millions de points sans la lire
  en entier.

Les temps de traitement sont longs: l'état (`pending`, `ready`, `failed`) fait partie de la version, et une tâche n'est
pas ouverte sur un fichier non prêt.

## 5. Agrégation, accord et export

Plusieurs annotateurs travaillent sur le même élément. Rien n'est résolu à l'écriture.

| Tâche | Agrégation | Mesure d'accord |
|---|---|---|
| Classification d'élément | vote majoritaire, répartition des votes | κ de Cohen / Fleiss |
| Régression | moyenne, médiane, écart-type | écart-type par élément, corrélation |
| Segments, classification par régions | fusion des régions qui se recouvrent (intersection sur union temporelle ≥ seuil) et vote sur le label | IoU temporel, F-mesure à `collar` près |
| Diarisation | recalage des locuteurs entre annotateurs, puis vote | DER (taux d'erreur de diarisation) |
| Transcription | alignement des textes, choix du meilleur | WER entre annotateurs |
| Suivi d'objets | appariement des pistes par IoU image par image | IoU moyen, changements d'identité |
| Séries, segments | comme les segments, en indices | IoU temporel |

À décider avant l'export: le seuil d'IoU, le `collar` (tolérance de 0,25 s pour la diarisation, par exemple) et la règle
de départage (voir **8**).

**Formats d'export** (nouvelle configuration du dataset):

| Tâche | Formats usuels |
|---|---|
| Diarisation | **RTTM** |
| Transcription | **WebVTT**, SRT, ELAN (`.eaf`), **Praat TextGrid**, JSON segmenté (`{start, end, text, speaker}`) |
| Détection d'événements sonores | CSV `file, onset, offset, label` (DCASE), JSON AudioSet |
| Classification | colonne `label` (ou `labels`) dans le Parquet |
| Suivi d'objets | **MOT Challenge** (`frame, id, x, y, w, h`), COCO-vidéo, YouTube-VIS, CVAT XML |
| Segmentation temporelle d'actions | JSON ActivityNet / THUMOS (`{label, segment: [début, fin]}`) |
| Séries, étiquettes | CSV avec une colonne de label par point (les régions sont **étendues** point par point), ou JSON d'intervalles; format *Numenta Anomaly Benchmark* pour les anomalies |

Pour le suivi, l'export **échantillonne** les boîtes interpolées image par image, avec `box_at`.

## 6. Tâches possibles non faites

### Son
- **Diarisation dédiée**: modèle de tâche qui crée une piste par locuteur. Le frontend peut déjà le faire avec les
  segments étiquetés et les pistes, mais sans tâche nommée ni export RTTM. **Les locuteurs ne sont liés à une personne
  que pour un élément**: une liste de locuteurs au niveau du dataset (« Mme Martin », « conseiller 3 ») demande une table
  `speakers(dataset_id, name)` et un champ `speaker_id` sur les régions.
- **Détection d'événements et de mots-clés**: des **marqueurs ponctuels** (un instant plutôt qu'une plage). Aujourd'hui
  la durée minimale est de 0,05 s. Un type `point` serait une région avec `end = start`, ou une table à part.
- **Balises de transcription** (`[rire]`, `[inaudible]`, `[bruit]`), définies par la tâche et insérables d'un clic.
- **Alignement mot à mot**: une pré-transcription par un modèle, corrigée par l'annotateur. Stocker des `words`
  (`text`, `start`, `end`) sous la région.
- **Spectrogramme** à la place ou à côté de la forme d'onde, pour les sons où la fréquence compte (chants d'oiseaux).
- **Qualité d'enregistrement par critère** (bruit, clipping): plusieurs échelles, voir le document tabulaire.

### Vidéo
- **Suivi par polygones**: un polygone par image clé, interpolé entre deux. Il impose le **même nombre de points** à
  toutes les clés d'une piste. Prévoir `track_keyframes.points` (JSONB) à la place de `x1..y2`.
- **Segmentation spatiale vidéo** (masques): hors périmètre, très coûteux.
- **Relations entre objets** dans le temps (« la main prend le couteau »).
- **Ancrage temporel d'un texte**: une phrase, et l'annotateur désigne la plage de la vidéo qui la correspond (*temporal
  grounding*). Une région avec `text`, déjà supportée; il manque le mode « une requête, une plage ».
- **Description dense**: une phrase par plage, avec le texte déjà supporté sous `granularity = regions`.
- **Suivi assisté**: un modèle propose la boîte aux images intermédiaires et l'annotateur corrige. À brancher sur
  `annotations.source = 'model'`.

### Série temporelle
- **Correction d'un point isolé** (valeur fausse, valeur manquante), comme la revue de cellules d'un tableau, avec valeur
  corrigée et raison.
- **Plusieurs séries superposées** pour les comparer (même magasin, articles différents) et annoter ensemble.
- **Séries multivariées**: choisir la colonne annotée, ou annoter une région sur toutes.
- **Points de rupture** comme marqueurs ponctuels (comme les mots-clés du son).
- **Annotation d'une prévision**: tracer à la main la courbe attendue, ou valider une prévision proposée.
- **Étiquetage point par point** (chaque point a son label), en plus des régions: produit directement le format attendu
  par les modèles de détection d'anomalies.

## 7. Correspondance avec le frontend

| Fichier du frontend | Mock | Remplacé par |
|---|---|---|
| `audioMock.ts` → `clipFor` | échantillons et pics générés | `peaks_url`, `media_url` (Range) |
| `useAudioPlayer.ts` | lecture d'un `AudioBuffer` généré | `<audio>` ou Web Audio sur l'URL présignée |
| `useClockPlayer.ts`, `videoMock.ts`, `VideoFrame.tsx` | horloge et scène générée | `<video>` sur le proxy, `requestVideoFrameCallback` pour l'image courante |
| `seriesMock.ts` | séries générées, `dateAt` | `GET …/series/{id}?from&to&max_points` |
| `mockData.ts` → `Dataset.collection` | liste de séries | `dataset_series` |
| `store.ts` → `AudioSegment`, `ObjectTrack`, `Keyframe` | réponses en mémoire | corps de `PUT …/annotation` (**3**) |
| `Waveform.tsx` | construit la forme d'onde depuis un tableau complet | pics multi-résolution selon le zoom |
| `TimedWorkspace.tsx` | `rows = d.sample` ou `d.collection` | `GET /tasks/{id}/rows` paginé |

Conversions au branchement:
- **Indice de point → horodatage** pour les séries (et l'inverse en lecture).
- `label` / `labels` d'une région → `label_ids`.
- **Temps de la vidéo**: arrondi à 1/25 s dans le frontend; passer au `fps` réel renvoyé par l'API.
- Les `id` de régions et de pistes générés côté client deviennent des UUID serveur à la première écriture.

## 8. Ordre de construction proposé

1. **Médias et séries**: `dataset_files` enrichi (durée, fps…), `dataset_series`, tâche de fond pour les pics, les
   proxys et les résumés. Sans cela, rien ne peut être lu.
2. **Réponses au niveau de l'élément** (classification, description, régression) pour ces trois modalités: elles
   réutilisent le noyau du premier document, aucune table nouvelle sauf `annotation_captions`.
3. **Régions et pistes**: `annotation_regions`, `annotation_region_labels`, `config.tracks`. Débloque segments,
   transcription, détection et les versions « par passages ».
4. **Suivi d'objets**: `annotation_tracks`, `track_keyframes`, `box_at` et ses tests partagés.
5. **Agrégation, accord et exports** (RTTM, WebVTT, MOT, CSV d'intervalles).
6. **Plus tard**: marqueurs ponctuels, locuteurs partagés, alignement mot à mot, suivi par polygones, pré-annotation
   par un modèle.

Chaque étape: migration Alembic, tests, mise à jour de `docs/data-model.*`.

## 9. Questions ouvertes

1. **Locuteurs.** Une liste partagée au niveau du dataset (identifiants stables entre extraits) ou propre à chaque tâche
   (comme aujourd'hui)? Qui la tient à jour?
2. **Chevauchements sur une même piste.** On avertit seulement, ou on les interdit pour certaines tâches (transcription,
   où deux textes au même instant sur une piste n'ont pas de sens)?
3. **Marqueurs ponctuels.** Une région de durée nulle, ou un type distinct avec sa propre table?
4. **Longs fichiers.** Au-delà de quelques minutes (réunions, films), annote-t-on en **fenêtres** de 30 à 60 s avec
   chevauchement, ou le fichier entier? Cela change le modèle de tâche (une tâche porte-t-elle sur des fenêtres?).
5. **Fréquence des images.** Un fichier vidéo à fréquence variable: le proxy force-t-il une fréquence constante?
6. **Suivi.** Quand deux annotateurs ont des pistes différentes pour un même objet, qui décide quelles pistes sont les
   mêmes (appariement automatique par IoU, ou revue humaine)?
7. **Séries à pas irrégulier et fuseaux horaires.** L'horodatage est stocké en UTC; l'affichage suit-il le fuseau de
   l'utilisateur ou celui du dataset?
8. **Séries multivariées.** Une région s'applique-t-elle à toutes les colonnes ou à une seule?
9. **Stockage.** Les pics, proxys et vignettes sont-ils regénérés à chaque nouvelle version, ou partagés quand le fichier
   n'a pas changé (hash identique)?
10. **Coût.** Qui paie le traitement des médias (transcodage), et quelle est la taille maximale d'un fichier?
