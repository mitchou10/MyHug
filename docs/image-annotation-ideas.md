# Annotation d'images: tâches possibles et comment les ajouter

Ce document garde en tête ce qui est **possible** pour l'annotation d'images, et détaille **comment** l'ajouter au
frontend actuel (puis au backend). Il ne décrit pas du code déjà écrit: pour cela, voir
[backend-datasets.md](backend-datasets.md) et [backend-tabular-annotation.md](backend-tabular-annotation.md).

## 1. Où on en est

Tâches image déjà faites dans `frontend/src/features/datasets/annotation/`:

| Type de tâche | Outil | Réponse (`Answer`) |
|---|---|---|
| `image_detection` | polygone ou rectangle (en 4 points), un label par objet | `objects: ImageObject[]` |
| `image_segmentation` | polygone, régions remplies | `objects: ImageObject[]` |
| `image_polyline` | ligne ouverte (≥ 2 points) | `objects: ImageObject[]` |
| `image_keypoints` | points nommés, plusieurs instances, point masqué | `instances: KeypointInstance[]` |
| `image_classification` | un ou plusieurs labels (multi-label), raison | `label` / `labels`, `reason` |
| `image_caption` | une ou plusieurs descriptions | `captions: string[]` |
| `image_vqa` | plusieurs paires question / réponse par image | `qa: QAPair[]` |

Conventions déjà posées, **à respecter pour toute nouvelle tâche image**:

- **Coordonnées normalisées**: un point est `[x, y]` avec `x` et `y` entre 0 et 1 (fraction de la largeur et de la
  hauteur). Rien n'est stocké en pixels: l'annotation reste valable si l'image est redimensionnée.
- **Un label est identifié par son `id`**, jamais par son nom (renommer ne casse rien, supprimer garde les annotations).
- **Une réponse par annotateur et par image**, enregistrée en bloc avec « Valider ».
- Les formes sont dessinées dans un `<svg viewBox="0 0 largeur hauteur">`, ce qui rend le zoom et l'export simples.

## 2. Recette: ajouter une tâche image

Les étapes sont toujours les mêmes. Compter une demi-journée pour une variante d'un outil existant, plusieurs jours
pour un outil nouveau.

1. **`store.ts`**
   - Ajouter le type à `TaskType` et à `IMAGE_TASKS`.
   - Décrire la réponse: un nouveau type (comme `Keypoint`) et un champ optionnel dans `Answer`.
   - Ajouter une tâche d'exemple dans `state.projects`, sur le dataset `mitchou/street-signs`.
2. **Création de la tâche** (`NewProjectDialog.tsx`): décider si elle a besoin de labels (`needsLabels`), d'une échelle
   (comme la régression) ou de rien, et ajouter une phrase d'aide à l'étape 2 si nécessaire.
3. **Outil**: soit réutiliser `PolygonCanvas.tsx` (formes avec label), soit créer un composant (comme
   `KeypointsEditor.tsx`). `ImageWorkspace.tsx` choisit l'outil selon `task`.
4. **Traductions**: `datasets.annotation.tasks.<type>.{title,hint}` et les textes d'outil, dans `en.json` et `fr.json`.
5. **Backend**: voir **4** pour les tables, et ajouter la valeur à l'énumération `annotation_tasks.type`.

Ne pas oublier: les raccourcis clavier ne doivent pas entrer en conflit avec ceux de `ImageWorkspace.tsx`
(`1…9` labels, `V` `P` `R` outils, `Entrée`, `Échap`, `Suppr`).

## 3. Tâches possibles non faites

### 3.1 Boîtes englobantes orientées

- **À quoi ça sert**: textes penchés, véhicules vus du dessus, objets longs en diagonale.
- **Outil**: un rectangle qui peut pivoter. Comme pour le rectangle actuel, on trace une boîte par glisser, puis une
  poignée de rotation au-dessus de la forme.
- **Réutilisation**: `PolygonCanvas.tsx` et l'outil `rect`. Une boîte orientée reste un polygone à 4 points, déjà
  stockable dans `ImageObject`.
- **Ce qu'il faut ajouter**:
  - Une poignée de rotation (cercle au-dessus du centre du côté supérieur) qui applique une rotation aux 4 points autour
    du centre.
  - Un outil `obb` (touche `O`) dans `Tool`.
  - À l'enregistrement, on peut garder uniquement les 4 points: l'angle se déduit.
- **Backend**: aucune table nouvelle. À l'export, convertir en `(cx, cy, largeur, hauteur, angle)` si le format cible
  le demande (DOTA, COCO étendu).
- **Difficulté**: faible à moyenne.

### 3.2 OCR (reconnaissance de texte)

- **À quoi ça sert**: panneaux, plaques, documents, étiquettes.
- **Outil**: on encadre une zone de texte avec un polygone ou un rectangle, puis on **saisit son contenu**. Chaque zone a
  un champ texte, éventuellement une **valeur normalisée** avec les mêmes formats que les entités du texte
  (`format.ts`).
- **Réutilisation**: `PolygonCanvas.tsx` pour la forme, la liste d'objets de `ImageWorkspace.tsx` pour le champ, et la
  validation de format de l'extraction d'entités.
- **Ce qu'il faut ajouter**:
  - Un champ `text` (et `value`, `reason`) sur `ImageObject`.
  - Une option « un seul label » pour les tâches sans catégories: l'OCR peut se contenter d'un label unique « texte ».
  - Optionnel: indiquer la **langue**, le **sens de lecture** (les polygones imposent l'ordre des points) et une case
    « illisible ».
  - Pour aller plus vite: une pré-annotation par un modèle d'OCR, relue par l'annotateur (voir **5**).
- **Backend**: la table `image_objects` (voir **4**) gagne `text`, `value`, `legible`.
- **Difficulté**: moyenne.

### 3.3 Qualité de l'image

- **À quoi ça sert**: filtrer un dataset (flou, sous-exposition, bruit, recadrage), ou évaluer des images générées.
- **Outil**: une ou plusieurs **échelles** (par exemple netteté de 1 à 5, exposition de 1 à 5), ou une régression simple.
- **Réutilisation**: totale. C'est la régression existante (`ScaleInput.tsx`, `ScaleForm.tsx`, `Scale`) appliquée
  à une image. Pour plusieurs critères, créer une tâche par critère, ou étendre la tâche à une **liste de critères**,
  chacun avec sa propre échelle.
- **Ce qu'il faut ajouter**: un type `image_quality` (ou autoriser `regression` pour la modalité image, ce qui est
  beaucoup plus simple), et le panneau avec un curseur par critère.
- **Backend**: `annotations.value` suffit pour un critère. Pour plusieurs critères, une table
  `annotation_scores(annotation_id, criterion_id, value)`.
- **Difficulté**: faible.

### 3.4 Comparaison de deux images

- **À quoi ça sert**: préférence entre deux versions (génération, compression), détection de doublons, « même objet ou non ».
- **Outil**: deux images côte à côte et une réponse: `A`, `B`, `égales`, ou `oui` / `non` pour une question.
- **Réutilisation**: `SceneGraphics` pour afficher, les boutons de labels de `ImageWorkspace.tsx` pour la réponse, la
  raison facultative.
- **Ce qu'il faut ajouter**:
  - Un dataset dont **chaque ligne est une paire** (`image_a`, `image_b`). Cela touche le modèle de données: une ligne
    référence deux fichiers.
  - Le choix de la réponse: labels fixes (`A meilleur`, `B meilleur`, `égalité`) ou texte libre.
  - Mélanger l'ordre A/B à l'affichage pour éviter le biais de position (et stocker l'ordre réellement montré).
- **Backend**: `dataset_rows` doit pouvoir référencer plusieurs fichiers; l'annotation est une classification ordinaire
  (`label_id`, `reason`) plus `shown_order`.
- **Difficulté**: moyenne (surtout à cause du modèle de données).

### 3.5 Relations entre objets

- **À quoi ça sert**: scènes (« personne sur vélo », « voiture devant panneau »), graphes de scène, documents
  (« en-tête → tableau »).
- **Outil**: on trace d'abord les objets (détection ou segmentation), puis on **relie deux objets** par un lien nommé:
  clic sur le premier objet, clic sur le second, choix du type de relation.
- **Réutilisation**: `PolygonCanvas.tsx` (sélection d'objets), la liste d'objets, et la notion de label (les types de
  relation sont des labels).
- **Ce qu'il faut ajouter**:
  - Un tableau `relations: { id, from, to, label }[]` dans `Answer`, qui référence des `ImageObject.id`.
  - Un outil `link` dans `Tool` qui dessine une flèche entre deux objets.
  - La suppression d'un objet supprime ses relations (ou demande confirmation).
  - Les types de relation sont une **liste de labels distincte** de celle des objets: soit une deuxième liste dans la
    tâche, soit une tâche dédiée « relations » qui part d'objets déjà annotés.
- **Backend**: table `image_relations(annotation_id, from_object_id, to_object_id, label_id)`. Contrainte: les deux
  objets appartiennent à la même annotation.
- **Difficulté**: moyenne à élevée. À faire en même temps que les relations entre entités du texte pour avoir un seul
  concept de « relation ».

### 3.6 Segmentation par pinceau (masque au pixel)

- **À quoi ça sert**: segmentation fine (cheveux, végétation, formes très irrégulières), imagerie médicale.
- **Outil**: pinceau et gomme avec une taille réglable, un calque par label, et idéalement un « remplissage » (pot de
  peinture) et un outil assisté (SAM, voir **5**).
- **Réutilisation**: très peu. Il faut un **canevas bitmap** (`<canvas>` HTML) en plus du SVG, puis une conversion
  masque ↔ polygone si on veut aussi exporter en polygones.
- **Ce qu'il faut ajouter**:
  - Un composant de peinture avec calques par label, annuler / rétablir et zoom (le zoom devient indispensable).
  - Un format de stockage **compact**: RLE (COCO) ou PNG indexé. Jamais un tableau de pixels en JSON.
  - Un état partagé avec le reste du frontend: pour garder `Answer` léger, stocker une **référence** (`mask_key`) et
    envoyer le masque par un autre appel.
- **Backend**: masques dans le stockage objet (`datasets/{id}/annotations/{annotation_id}/mask.png`), table
  `image_masks(annotation_id, label_id, storage_key, format)`. Prévoir une limite de taille.
- **Difficulté**: élevée. À ne faire que si les polygones ne suffisent pas.

### 3.7 Suivi d'objets dans une vidéo

- **À quoi ça sert**: suivre un objet image par image (piétons, véhicules, sport).
- **Outil**: c'est de la **vidéo**, pas de l'image: une timeline, des images clés, et l'interpolation des boîtes entre
  deux images clés.
- **Ce qu'il faut ajouter**: une modalité à part entière avec lecteur vidéo, notion de temps dans les coordonnées
  (`frame`, `t`), et objets avec identifiants de piste (`track_id`).
- **Backend**: tables `video_tracks` et `video_track_points(track_id, frame, bbox ou polygone)`.
- **Difficulté**: élevée. À traiter dans le chantier vidéo, pas dans celui de l'image.

### 3.8 Autres idées

- **Attributs sur les objets** (occlus, tronqué, difficile, couleur): des cases à cocher par objet. Très simples,
  très utiles pour filtrer à l'export. Un champ `attributes: Record<string, boolean | string>` sur `ImageObject`,
  défini par la tâche.
- **VQA ancrée**: en plus de la réponse, désigner la **région** de l'image qui la justifie (comme la source surlignée
  du texte). Un rectangle ou polygone par paire, stocké dans `QAPair.region`.
- **Image vers texte avec contraintes**: longueur minimale, langue, ou liste de mots obligatoires, pour guider les
  annotateurs.
- **Profondeur et saillance**: annotations denses, mal adaptées à un outil manuel. À éviter, sauf avec assistance
  d'un modèle.
- **Revue**: afficher côte à côte les annotations de deux annotateurs sur la même image, pour trancher.

## 4. Backend: modèle commun des annotations d'image

Les tâches faites et à venir se rangent dans quelques tables. Elles prolongent celles de
[backend-datasets.md](backend-datasets.md), qui sont déjà prévues pour le texte et le tabulaire.

**`image_objects`** (détection, segmentation, lignes, OCR, boîtes orientées)
- `id`, `annotation_id`, `label_id`, `kind` (`polygon` | `polyline`), `points` (`JSONB`, liste de `[x, y]` entre 0 et 1,
  ou `geometry` PostGIS), `reason`, `attributes` (`JSONB`), `text` et `value` (OCR, nullable).
- Pas de table par point: un objet est lu et écrit d'un bloc.
- Validation: `points` entre 0 et 1, au moins 3 points pour un polygone, 2 pour une ligne, au plus ~500 points (limite
  configurable).

**`image_keypoints`**
- `id`, `annotation_id`, `instance` (entier), `label_id`, `x`, `y`, `occluded`.
- Unique `(annotation_id, instance, label_id)`.

**Classification, légendes, VQA**: elles réutilisent `annotations.label_id`/`labels` (multi-label: table
`annotation_choices`), `annotations` + une table `image_captions(annotation_id, position, text)`, et `qa_pairs` du texte
(sans `qa_sources`).

**Fichiers**: les images viennent du stockage objet (URLs présignées). L'API de lignes renvoie `width` et `height`, ce
qui permet de dessiner sans charger l'image côté serveur.

**Exports** (nouvelle configuration du dataset):

| Tâche | Formats usuels |
|---|---|
| Détection | COCO (`bbox` déduite du polygone), YOLO (boîtes normalisées), Pascal VOC |
| Segmentation | COCO (`segmentation` en polygones), masques PNG (rasterisation côté serveur) |
| Lignes | GeoJSON `LineString`, ou COCO avec `iscrowd=0` |
| Points clés | COCO keypoints (`[x, y, v]`, `v` = 0, 1 ou 2 selon masqué ou visible) |
| Classification | une colonne `label` (ou `labels`) dans le Parquet |
| Légendes, VQA | JSONL `{image, caption(s)}` ou `{image, question, answer}` |

Les exports convertissent les coordonnées normalisées en pixels avec la largeur et la hauteur de l'image.

## 5. Assistance par un modèle (plus tard)

Prévue dans le modèle de données (`annotations.source = 'model'`), pas dans l'interface. Les outils d'image qui y gagnent
le plus:

- **Segmentation assistée (SAM ou équivalent)**: un clic sur l'objet produit un polygone, l'annotateur le corrige.
- **Détection**: un modèle propose les boîtes, l'annotateur supprime ou corrige.
- **OCR**: un moteur de reconnaissance propose le texte de chaque zone.
- **Légendes**: un modèle propose une description, relue et corrigée.

Règle: la proposition d'un modèle est toujours une **annotation en brouillon**, jamais une annotation validée, et elle
garde sa provenance.

## 6. Améliorations de l'outil de dessin à prévoir

À traiter avant d'annoter de vraies images:

- **Zoom et déplacement** (molette, glisser avec espace). Aujourd'hui l'image est affichée à la largeur du panneau, ce
  qui rend les petits objets difficiles à tracer.
- **Insertion d'un point** sur un côté d'un polygone existant, et suppression d'un point (clic droit).
- **Annuler / rétablir** (`Ctrl+Z`) sur toute l'image, pas seulement sur le tracé en cours.
- **Aimantation** des points proches et des bords de l'image.
- **Copier les formes** de l'image précédente (utile pour des scènes qui se ressemblent).
- **Grandes images**: affichage par tuiles ou par niveaux de zoom; le SVG par-dessus fonctionne toujours, car il est
  indépendant de la résolution.
- **Performance**: au-delà de ~200 formes par image, ne dessiner que les formes visibles et simplifier les polygones
  à l'affichage.

## 7. Questions ouvertes

1. **Détection avec polygones ou boîtes?** On accepte les deux. Faut-il imposer un seul format par tâche (une tâche
   « détection » exigerait des boîtes, une tâche « segmentation » des polygones)?
2. **Plusieurs tâches sur la même image.** Quand une même image reçoit détection, légende et classification, a-t-on
   une annotation par tâche (comme aujourd'hui), ou un « formulaire » qui regroupe plusieurs tâches?
3. **Taille des polygones.** Quel nombre maximal de points par forme et de formes par image accepte-t-on?
4. **Attributs.** Sont-ils définis par tâche (liste libre) ou par label?
5. **Images d'une série** (vidéo découpée en images, imagerie médicale en coupes): chaque image est-elle une ligne
   indépendante, ou une partie d'un groupe qu'on annote ensemble?
