# Backend des données tabulaires et de la régression

Complète [backend-datasets.md](backend-datasets.md), qui décrit les datasets, les tâches d'annotation et le texte.
Ce document ne répète pas ce qui y est déjà: il ajoute ce que demandent **les datasets tabulaires** et **la
régression** (texte et tabulaire). Les conventions (couches, `Actor`, UUID, Alembic, pas de table `users`) sont
celles du premier document.

## 1. Ce que le frontend fait aujourd'hui

**Tâches tabulaires** (grille plein écran, panneau à droite, enregistrement au fil de l'eau):

| Tâche | Ce que fait l'annotateur | Réponse |
|---|---|---|
| `row_label` | choisit un label pour une ligne (normale, suspecte, doublon…), raison facultative | `label`, `reason` |
| `cell_review` | signale une cellule (erreur, manquante, aberrante, format), donne la valeur corrigée et une raison | `cells[colonne] = { issue, corrected, reason }` |
| `column_schema` | décrit une colonne: rôle, type, formats, unité, description | `columns[colonne] = { role, valueType, formats, unit, description }` |

**Régression** (`regression`, pour le texte et le tabulaire): un nombre par texte ou par ligne, sur une échelle
définie par le créateur de la tâche (`min`, `max`, `step`, `unit`, légende de chaque extrémité), raison facultative.

Les fichiers concernés: `features/datasets/annotation/TabularWorkspace.tsx`, `ScaleInput.tsx`, `ScaleForm.tsx`,
`store.ts` (types `CellNote`, `ColumnNote`, `Scale`, `Answer`).

## 2. Changements au modèle de données

### 2.1 Types de tâche et configuration

`annotation_tasks.type` passe de `classification | ner | qa` à:

```
classification | ner | qa | regression | row_label | cell_review | column_schema
```

La configuration propre à un type ne doit pas multiplier les colonnes. Proposition: une colonne
`config JSONB` validée par un **modèle Pydantic par type** (union discriminée sur `type`), au lieu de colonnes
nullables:

| Type | `config` |
|---|---|
| `regression` | `{ "min": 0, "max": 10, "step": 0.5, "unit": "€", "min_label": "…", "max_label": "…" }` |
| `row_label`, `cell_review`, `column_schema`, `classification`, `ner` | `{}` (les labels sont dans `annotation_labels`) |
| `qa` | `{}` |

- Règles de validation de `regression`: `min < max`, `step > 0`, valeurs finies. Le `PATCH /tasks/{id}` peut changer
  l'échelle **sans toucher aux valeurs déjà données**: le frontend le promet à l'utilisateur. Les valeurs hors de la
  nouvelle échelle restent stockées; le service les marque `out_of_range` dans les statistiques (voir **5**).
- `row_label`, `cell_review` et `column_schema` réutilisent `annotation_labels` tel quel: les labels de `cell_review`
  sont les types de problème, ceux de `column_schema` sont les rôles. Les champs propres à l'extraction d'entités
  (`kind`, `value_type`, `formats`, `examples`) restent à `NULL` pour ces tâches.

### 2.2 Le schéma d'un dataset tabulaire

Le frontend suppose qu'un dataset tabulaire a un **schéma de référence** (`Dataset.schema`): ce que chaque colonne
doit contenir. Il sert à afficher le format attendu et à valider les valeurs corrigées. Il lui faut une vraie table:

**`dataset_columns`**
- `id`, `version_id`, `position` (ordre des colonnes), `name`, `dtype` (type physique: `string`, `int`, `float`,
  `bool`, `date`…), `value_type` (`text | date | number | identifier | amount`, le même vocabulaire que les labels
  d'entités), `formats` (tableau de texte), `unit`, `description`, `role` (facultatif), `is_row_key` (bool).
- Unique `(version_id, name)` et `(version_id, position)`. Au plus une colonne `is_row_key` par version.
- **À la création d'une version**: on déduit `dtype` du fichier (Parquet: depuis son schéma; CSV: sur un échantillon).
  `value_type`, `formats`, `unit`, `description` restent vides jusqu'à ce qu'un maintainer les remplisse, **à la main
  ou en acceptant une proposition issue d'une tâche `column_schema`** (voir **2.5**).
- `dataset_versions.null_tokens` (tableau de texte, par défaut `['', 'null', 'NaN', 'n/a']`): ce qui compte comme
  « valeur absente ». Les données d'exemple mélangent `''` et `'n/a'`; sans règle commune, « manquante » n'a pas de
  sens. Les valeurs sont stockées **telles que dans le fichier** et interprétées à la lecture.

### 2.3 Adresser une ligne et une colonne

- **Ligne**: `(split, row_index)` comme pour le texte, **plus `row_key`** (texte, nullable) quand le dataset a une
  colonne `is_row_key`. Si une nouvelle version réordonne les lignes, `row_key` permet de retrouver la ligne; sans clé,
  on retombe sur `text_sha256` (hash de la ligne entière), comme dans le premier document.
- **Colonne**: par **nom** de colonne, jamais par position. Le frontend utilise un indice, qu'il doit convertir avant
  l'appel. On garde aussi `column_position` à titre indicatif (une colonne renommée dans une version ultérieure ne
  casse pas l'annotation, qui garde son nom d'origine).
- Une annotation d'une version précédente dont la ligne a disparu est marquée `stale`, comme pour le texte.

### 2.4 Tables des annotations

**`annotations`** (existe déjà, voir le premier document): on y ajoute

- `value NUMERIC(20, 6)` (nullable): la valeur d'une régression. `NUMERIC` et non `float`, pour garder un pas de 0,05
  ou une valeur décimale sans erreur d'arrondi. Contrainte: `value` renseignée seulement si la tâche est `regression`.
- `row_key` (texte, nullable).

Pour `row_label`, on réutilise `label_id` et `reason`: **aucune table nouvelle**. Pour `regression`, `value` et `reason`.

**`annotation_cells`** (`cell_review`): plusieurs cellules par ligne annotée.
- `id`, `annotation_id`, `column_name`, `column_position`, `issue_label_id`, `original_value` (copie de la cellule telle
  qu'elle était, pour relire sans le dataset), `corrected_value` (texte, nullable), `reason`.
- Unique `(annotation_id, column_name)`. Une cellule sans problème n'a pas de ligne.
- `corrected_value` est du **texte**: la bonne valeur peut ne pas être un nombre (`« Lyon »` au lieu de `« lyon »`).
  Le type réel vient de `dataset_columns`.

**`column_annotations`** (`column_schema`): **pas rattachée à une ligne**, donc pas dans `annotations`.
- `id`, `task_id`, `annotator`, `annotator_username`, `column_name`, `role_label_id`, `value_type`, `formats`
  (tableau), `unit`, `description`, `created_at`, `updated_at`.
- Unique `(task_id, annotator, column_name)`.
- Le frontend les range aujourd'hui à la « ligne 0 » du store. À la migration, c'est cette table, pas `row_index = 0`.

### 2.5 Du schéma annoté au schéma de référence

Une tâche `column_schema` **propose**, elle ne modifie pas le schéma du dataset toute seule:

1. Les annotateurs remplissent `column_annotations`.
2. Un maintainer ouvre une vue de synthèse (`GET /tasks/{id}/columns/summary`) qui montre, colonne par colonne, les
   propositions (rôle, type, formats, unité, description) et leurs désaccords.
3. Il accepte une proposition: `POST /tasks/{id}/columns/{name}/apply` écrit dans `dataset_columns` de la dernière
   version.

C'est la seule façon pour qu'une annotation modifie des métadonnées du dataset. Tout le reste reste une couche à part.

## 3. API (ajouts)

Les routes de tâche, de liste de lignes et d'annotation du premier document gardent leur forme. Ajouts:

**Schéma**
- `GET /datasets/{owner}/{name}/schema` : colonnes de la dernière version (`dataset_columns`).
- `PUT /datasets/{owner}/{name}/schema` : le maintainer édite types, formats, unités, descriptions, colonne clé.

**Lignes d'un dataset tabulaire**
- `GET /tasks/{id}/rows?offset=&limit=&filter=&sort=` renvoie
  `{ columns: [...], rows: [{ row_index, row_key, values: [...], annotation }], total }`.
  - `limit` ≤ 200. Le frontend charge **toutes** les lignes d'un échantillon aujourd'hui; avec 85 000 lignes, il faudra
    une grille virtualisée qui demande des fenêtres successives.
  - `filter`: `all | todo | done | flagged` (lignes où il y a au moins une cellule signalée, pour `cell_review`).
  - `sort`: par colonne et sens, pour retrouver une valeur aberrante (voir **7**).
  - `annotation` est **mon** annotation de la ligne (ou `null`), pas celle des autres.

**Annotation d'une ligne** : `PUT /tasks/{id}/rows/{split}/{row_index}/annotation`, idempotent. Corps selon la tâche:

```jsonc
// row_label
{ "label_id": "…", "reason": "…" }

// regression
{ "value": 7.5, "reason": "…" }

// cell_review
{ "cells": [
    { "column": "surface_m2", "issue_label_id": "…", "corrected_value": "54", "reason": "…" }
] }
```

- `cell_review`: le `PUT` **remplace** la liste des cellules signalées de cette ligne. Le service remplit
  `original_value` à partir de la ligne, jamais à partir du client.
- `regression`: refus (422) si `value` est hors de `[min, max]` de l'échelle courante; **pas** de refus si elle n'est pas
  un multiple exact de `step` (le champ numérique du frontend est libre), mais le service arrondit à 6 décimales.
- Une annotation vide (aucun label, aucune valeur, aucune cellule) est supprimée plutôt qu'enregistrée.

**Annotation d'une colonne**
- `GET /tasks/{id}/columns` : mes annotations de colonnes.
- `PUT /tasks/{id}/columns/{column_name}` : crée ou remplace la mienne (idempotent).

**Enregistrement automatique**: le frontend enregistre à chaque modification. Il enverra donc un `PUT` à chaque frappe
s'il n'est pas contenu. Règles côté client: **débattement d'environ 500 ms** par ligne ou colonne, et un seul `PUT` en
vol par ressource. Côté serveur, le `PUT` est idempotent et léger (pas de recalcul global dans la requête).

## 4. Validation des formats, côté serveur

La valeur corrigée d'une cellule (et la valeur normalisée d'une entité) est vérifiée contre les `formats` du schéma. Le
**langage de format est celui du frontend** (`annotation/format.ts`) et le serveur doit se comporter à l'identique:

- Dates: `YYYY`, `YY`, `MM`, `DD`, `HH`, `mm`, `ss`.
- Autres types: `D` chiffre, `A` lettre, `X` lettre ou chiffre, `+` derrière l'un d'eux = un ou plusieurs; le reste est littéral.
- Plusieurs formats: la valeur est acceptée si **l'un** d'eux correspond.

Un seul module, `app/services/formats.py`, avec des **vecteurs de test partagés** entre Python et TypeScript, pour
qu'ils ne divergent pas:

| Format | Type | Valeur | Attendu |
|---|---|---|---|
| `YYYY-MM-DD` | date | `2023-03-12` | accepté |
| `YYYY-MM-DD` | date | `12/03/2023` | refusé |
| `DDDDDDD` | identifier | `2301457` | accepté |
| `DDDDDDD` | identifier | `23014` | refusé |
| `D+.DD` | amount | `18000.00` | accepté |
| `D+.DD` | amount | `18000,00` | refusé |

Comportement: **un avertissement, pas une erreur**. L'API renvoie la valeur enregistrée et un champ `warnings`
(`[{ "field": "cells[0].corrected_value", "code": "format_mismatch", "formats": [...] }]`). Le frontend ne bloque pas
non plus.

## 5. Agrégation, statistiques et export

Plusieurs annotateurs travaillent sur les mêmes lignes. Rien n'est résolu au moment de l'annotation; tout se décide à
la lecture ou à l'export.

| Tâche | Résumé par ligne | Export (colonne ajoutée à la nouvelle config) |
|---|---|---|
| `row_label` | label majoritaire, répartition des votes | `label`, `label_agreement` (part de votes pour le gagnant) |
| `regression` | moyenne, médiane, écart-type, nombre de votes | `value` (moyenne ou médiane, au choix de l'export), `value_std`, `value_n` |
| `cell_review` | pour chaque cellule: problèmes signalés et corrections proposées | fichier de **corrections** `(row_key, colonne, valeur d'origine, valeur corrigée, problème)` |
| `column_schema` | propositions par colonne et désaccords | pas d'export de données: alimente `dataset_columns` (voir **2.5**) |

- **Régression**: l'accord entre annotateurs se mesure par l'écart-type par ligne dans un premier temps, puis par
  un coefficient (corrélation, ICC) plus tard. Les lignes avec un écart-type élevé sont proposées à la revue.
- **Export de `cell_review`**: deux sorties possibles, à ne pas confondre: le fichier de corrections (toujours), et une
  **version « nettoyée »** du dataset où les corrections acceptées sont appliquées (seulement sur demande d'un
  maintainer). La version nettoyée est une **nouvelle version**: les données d'origine ne sont jamais modifiées.
- **Cellule « manquante »**: elle reste une annotation. Remplacer un manquant par une valeur est une correction,
  traitée comme les autres, jamais une imputation automatique.
- Les statistiques de `GET /tasks/{id}/progress` ajoutent, pour la régression: histogramme des valeurs données,
  `min`, `max`, moyenne, et le nombre de valeurs `out_of_range` depuis un changement d'échelle.

## 6. Permissions

Mêmes règles que le premier document, avec une précision: **modifier l'échelle** d'une régression est réservé à la
même population que « modifier les labels » (créateur de la tâche, maintainer, admin). Appliquer une proposition de
schéma (`/columns/{name}/apply`) et publier une version nettoyée demandent le rôle **maintainer**, jamais seulement
annotateur.

## 7. Volumétrie et performance

- Un dataset tabulaire est lu **par fenêtre**: pour Parquet, par groupes de lignes (`pyarrow`), pour un CSV volumineux
  via un index d'offsets construit à la création de la version (ou DuckDB). Jamais de fichier chargé en entier par une
  requête.
- Les tris et filtres de `rows` s'exécutent sur le fichier (DuckDB lit Parquet et CSV directement). Pour
  `filter=flagged`/`done`/`todo`, on joint avec les annotations de l'utilisateur en base: prévoir
  l'index `annotations(task_id, annotator, row_index)`.
- `annotation_cells` peut grossir vite (jusqu'à plusieurs colonnes par ligne): index sur `(annotation_id)` et sur
  `(column_name, issue_label_id)` pour les statistiques par colonne.
- **Côté frontend**: la grille doit être **virtualisée** (une librairie de type `@tanstack/react-virtual`) avant de
  brancher des datasets réels. Le tableau actuel affiche toutes ses lignes.

## 8. Ce que le frontend mocke (et par quoi le remplacer)

| Fichier | Mock | Remplacé par |
|---|---|---|
| `mockData.ts` → `Dataset.schema` et `sample` | schéma et lignes de `house-prices` | `GET …/schema`, `GET /tasks/{id}/rows` |
| `store.ts` → `Answer.cells` | notes de cellules par **indice** de colonne | `annotation_cells`, par **nom** de colonne |
| `store.ts` → `Answer.columns` (rangé à la ligne 0) | notes de colonnes | `column_annotations` |
| `store.ts` → `Answer.value`, `AnnotationProject.scale` | valeur et échelle de la régression | `annotations.value`, `annotation_tasks.config` |
| `TabularWorkspace.tsx` | tout l'échantillon en mémoire, enregistrement immédiat | fenêtres de lignes + enregistrement débattu |
| `format.ts` | validation des formats | garder côté client, **dupliquer** côté serveur (**4**) |

Conversions à prévoir au branchement:
- **Indice de colonne → nom** (`d.columns[c]`), dans les deux sens.
- **Ligne 0 des colonnes → `column_annotations`**.
- **Échelle**: le frontend garde des chaînes dans ses champs (`ScaleDraft`) et envoie des nombres.
- Les identifiants de labels des tâches tabulaires viennent du serveur, comme pour le texte.

## 9. Ordre de construction

1. **Schéma d'un dataset tabulaire**: `dataset_columns`, déduction du `dtype`, `null_tokens`, `GET/PUT …/schema`.
   Sans cela, ni les formats attendus ni les colonnes n'existent côté serveur.
2. **Lecture par fenêtre**: `GET /tasks/{id}/rows` pour Parquet puis CSV, avec `limit`, `filter`, `sort`.
3. **`row_label`** (le plus simple, ne demande aucune table nouvelle) et **`regression`** (`annotations.value`,
   `config`, validation de l'échelle).
4. **`cell_review`**: `annotation_cells`, validation des formats avec avertissement.
5. **`column_schema`**: `column_annotations`, synthèse et `apply`.
6. **Agrégation et exports**: votes, moyenne et écart-type, fichier de corrections, version nettoyée.
7. **Plus tard**: mesure d'accord (coefficient), revue des désaccords, pré-annotation (un modèle propose une valeur
   ou un label; `annotations.source = 'model'`).

Chaque étape: migration Alembic, tests, mise à jour de `docs/data-model.*`.

## 10. Questions ouvertes

1. **Clé de ligne.** Impose-t-on une colonne identifiante par dataset tabulaire (`is_row_key`), ou accepte-t-on
   `row_index` seul et des annotations « fragiles » quand le fichier change?
2. **Valeurs absentes.** Qui définit `null_tokens`: le maintainer à la création, ou une détection automatique à valider?
3. **Régression.** Faut-il une valeur **par ligne et par annotateur** uniquement, ou aussi une **incertitude**
   (intervalle, niveau de confiance) à saisir? Faut-il plusieurs cibles (plusieurs échelles) sur une même ligne,
   ce qui revient à plusieurs tâches, ou à une tâche multi-valeurs?
4. **Corrections de cellules.** L'annotateur peut-il corriger **une autre colonne** que celle qu'il signale
   (par exemple signaler `surface_m2` et corriger `price_eur`)? Le frontend ne le permet pas aujourd'hui.
5. **Version nettoyée.** Qui peut la publier, et faut-il une revue obligatoire avant (deux annotateurs d'accord)?
6. **Données sensibles.** Un tableau contient souvent des données personnelles (noms, adresses). Faut-il un
   marquage des colonnes sensibles, qui masque leur valeur dans l'interface d'annotation ou limite l'export?
7. **Types de colonnes.** Pour les formats, le vocabulaire (`text`, `date`, `number`, `identifier`, `amount`) suffit-il
   (pas d'`email`, de `phone`, de code postal), ou ajoute-t-on des types prédéfinis avec leur format?
8. **Autres modalités.** Les tâches `regression` et `row_label` sont-elles génériques (une ligne = une image, un clip
   audio…) ou propres au texte et au tabulaire? À décider avant de figer `annotation_tasks.type`.
