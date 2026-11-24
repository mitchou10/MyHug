# Backend des datasets: cahier des charges

Ce document fixe ce que le backend devra faire pour les datasets et l'annotation, tel que le frontend le montre déjà
(avec des données mockées). Il sert de référence avant d'écrire la première ligne du backend.
Les **datasets tabulaires** et la **régression** sont traités à part dans [backend-tabular-annotation.md](backend-tabular-annotation.md).

- Les décisions déjà prises sont dans **1**.
- Le modèle de données est dans **3**, l'API dans **5**.
- Ce que le frontend mocke aujourd'hui, et par quoi le remplacer, est dans **9**.
- Les questions encore ouvertes sont dans **11**: à trancher avant de coder.

## 1. Décisions déjà prises

- **Les données brutes ne changent jamais.** Une annotation est une couche posée par-dessus un dataset, jamais une
  modification de ses fichiers. Un dataset est versionné; les lignes ont des identifiants stables.
- **Qui annote.** Toute personne ayant accès à un dataset peut annoter, sur n'importe quelle tâche de ce dataset.
  Une tâche est créée par un utilisateur et visible de tous ceux qui ont accès au dataset.
- **Qui modifie les labels.** Seul le créateur de la tâche (et un admin) peut ajouter, renommer, décrire ou supprimer
  des labels. Supprimer un label ne supprime pas les annotations déjà faites: elles gardent le label, marqué supprimé.
- **Une modalité par dataset**: text, image, audio, video, tabular, timeseries. Chaque modalité a son aperçu.
  Pour l'instant, **seul le texte s'annote**; les autres modalités reprendront le même cadre plus tard.
- **Pré-annotation par un modèle: plus tard.** Le modèle de données doit simplement ne pas l'empêcher
  (voir `source` dans la table `annotations`).
- **Plusieurs annotateurs** peuvent annoter la même ligne. Chacun a sa propre annotation. Le calcul de l'accord entre
  annotateurs et la revue sont hors périmètre de la première version, mais le modèle les permet.

## 2. Conventions du backend existant à respecter

Le backend est un template FastAPI organisé en couches. On garde exactement la même organisation.

| Couche | Dossier | Rôle |
|---|---|---|
| Modèles | `app/models/` | SQLAlchemy 2, un fichier par table, `Base` de `models/base.py` (noms de contraintes normalisés) |
| Repositories | `app/repositories/` | Accès à la base, sans règle métier |
| Services | `app/services/` | Règles métier, permissions, transactions |
| Routers | `app/routers/` | HTTP uniquement; l'injection se fait dans `routers/deps.py` |
| Schemas | `app/schemas/` | Modèles Pydantic d'entrée et de sortie |
| Stockage | `app/storage/` | `ObjectStore` (S3, RustFS en dev) obtenu avec `get_store` |

Autres règles à reprendre:

- **Pas de table `users`.** Le fournisseur d'identité (Keycloak) possède les comptes. On stocke le `sub` (`created_by`)
  et le nom que la personne avait à ce moment-là (`created_by_username`), comme `feedbacks`.
- **Identifiants**: `Uuid` (`uuid.uuid4`). **Dates**: `DateTime(timezone=True)` avec `server_default=func.now()`.
- **Migrations**: Alembic, une migration par module (voir `migrations/versions/`), jamais de `create_all`.
- **Permissions**: un service d'accès par ressource, sur le modèle de `services/access.py` (`FeedbackAccess`),
  qui reçoit un `Actor` (`user_id`, `username`, `is_admin`). Les routes ne testent jamais les rôles elles-mêmes.
- **Erreurs**: celles de `services/errors.py`, converties en HTTP par `routers/errors.py`.
- **Pagination**: par curseur (`services/cursor.py`), comme les listes de feedback.
- **Tests**: pytest, `moto` pour S3, une base réelle (voir `tests/conftest.py`). Chaque service est testé sans HTTP,
  chaque route a au moins un test de permission.

## 3. Modèle de données

```
datasets ──< dataset_versions ──< dataset_files
   │              └──< dataset_splits
   ├──< dataset_members          (qui a accès)
   ├──< dataset_likes
   └──< annotation_tasks ──< annotation_labels
              └──< annotations (une par ligne et par annotateur)
                       ├──< annotation_spans   (extraction d'entités)
                       └──< qa_pairs ──< qa_sources
```

### 3.1 Datasets

**`datasets`**
- `id`, `owner` (nom d'espace: utilisateur ou organisation, unique avec `name`), `name` (slug: `[a-z0-9-_.]`),
  `description`, `modality` (enum), `language`, `license`, `tags` (tableau de texte ou table de jointure),
  `visibility` (`public` | `private`), `card` (le README en markdown), `latest_version_id`.
- `created_by`, `created_by_username`, `created_at`, `updated_at`.
- Compteurs dénormalisés pour la liste: `downloads`, `likes_count` (mis à jour par le service, pas par des triggers).
- Contrainte unique sur `(owner, name)`: c'est l'adresse `/datasets/:owner/:name` du frontend.

**`dataset_versions`**: `id`, `dataset_id`, `number` (1, 2, 3…), `rows`, `size_bytes`, `created_by`, `created_at`.
Une nouvelle version est créée à chaque dépôt de fichiers; les anciennes restent lisibles.

**`dataset_files`**: `id`, `version_id`, `path` (ex. `data/train.parquet`), `size_bytes`, `sha256`, `storage_key`
(la clé dans le bucket, voir **6**), `content_type`.

**`dataset_splits`**: `id`, `version_id`, `name` (`train`, `test`…), `rows`, `file_id`.

**`dataset_members`**: `dataset_id`, `user_id` (`sub`), `role` (`reader` | `annotator` | `maintainer`), `added_by`.
- Un dataset `public` est lisible et annotable par tout utilisateur connecté.
- Un dataset `private` n'est accessible qu'à son propriétaire et à ses membres.
- « A accès » = peut lire. Le frontend n'a qu'un niveau (accès = peut annoter); on garde `role` pour pouvoir
  distinguer plus tard sans migration.

**`dataset_likes`**: `(dataset_id, user_id)` unique.

### 3.2 Adresser une ligne

Une annotation doit pointer sans ambiguïté vers une ligne d'une version. On utilise `row_ref`:

- `split` (texte) + `row_index` (entier, position dans le split) + `version_id`.
- On garde aussi `text_sha256` (hash du texte annoté) dans l'annotation. Si le dataset change, on sait quelles
  annotations ne correspondent plus.

Les **tâches pointent vers un dataset, pas vers une version**: elles suivent la dernière version. Si une ligne
disparaît ou change, ses annotations restent mais sont marquées `stale` (voir `annotations.stale`).

### 3.3 Tâches d'annotation

**`annotation_tasks`**
- `id`, `dataset_id`, `name`, `type` (`classification` | `ner` | `qa`), `status` (`open` | `closed`).
- `created_by`, `created_by_username`, `created_at`, `updated_at`.
- Options futures: `multi_label` (classification multi-label), `row_filter` (annoter un sous-ensemble).

**`annotation_labels`** (classification et extraction; vide pour `qa`)
- `id`, `task_id`, `name`, `description`, `position` (ordre d'affichage et touches 1, 2, 3…).
- `kind`: `entity` | `semantic` (extraction seulement). `entity` = une unité (nom, date); `semantic` = un sens métier
  souvent plus long (infraction, peine).
- `value_type`: `text` | `date` | `number` | `identifier` | `amount`.
- `formats`: tableau de texte. Plusieurs formats acceptés par label. Syntaxe: pour une date `YYYY YY MM DD HH mm ss`;
  pour les autres types `D` chiffre, `A` lettre, `X` lettre ou chiffre, `+` = un ou plusieurs, le reste littéral.
  Exemples: `YYYY-MM-DD`, `DDDDDDD`, `D+.DD`.
- `examples`: tableau de texte.
- `deleted_at` (nullable): **suppression logique**. Un label supprimé n'apparaît plus dans l'interface mais reste
  référencé par les annotations existantes.
- Unicité du nom parmi les labels non supprimés d'une tâche (index partiel).
- Renommer ou décrire un label change la ligne; l'`id` ne change jamais. C'est ce qui rend le renommage gratuit.

### 3.4 Annotations

**`annotations`**: une par `(task_id, row_ref, annotator)`, contrainte unique.
- `id`, `task_id`, `split`, `row_index`, `version_id`, `text_sha256`.
- `annotator` (`sub`), `annotator_username`.
- `status`: `draft` | `submitted` (plus tard `validated` | `rejected`).
- `source`: `human` (plus tard `model`, pour la pré-annotation).
- `stale` (bool), `created_at`, `updated_at`.
- Classification: `label_id` (nullable) et `reason` (texte libre, facultatif). Pour la classification multi-label
  future, on passera à une table `annotation_choices`.

**`annotation_spans`** (extraction d'entités)
- `id`, `annotation_id`, `label_id`, `start_char`, `end_char` (**offsets en caractères** dans le texte, fin
  exclue), `text` (copie du passage pour pouvoir relire sans le dataset), `value` (valeur normalisée, facultative),
  `reason` (facultatif).
- **Les spans peuvent se chevaucher**, et un même passage peut porter plusieurs labels: aucune contrainte
  d'exclusion en base. Seul le doublon exact `(annotation_id, start_char, end_char, label_id)` est interdit.
- Le frontend travaille aujourd'hui avec des **indices de mots**; l'API doit échanger des **offsets en caractères**,
  indépendants de la façon de découper. Le frontend fera la conversion (`mots → caractères`).
- Le service valide `value` contre les `formats` du label et **renvoie un avertissement, pas une erreur**:
  le frontend n'empêche pas non plus la validation. Garder la valeur telle que l'annotateur l'a saisie.

**`qa_pairs`** (question-réponse): plusieurs paires par annotation.
- `id`, `annotation_id`, `position`, `question`, `answer`, `answer_start_char` / `answer_end_char` (nullables:
  renseignés quand la réponse a été sélectionnée dans le texte, vides si elle a été tapée à la main), `reason`.

**`qa_sources`**: `id`, `pair_id`, `start_char`, `end_char`, `text`. Plusieurs sources par paire, qui peuvent se
chevaucher entre paires.

Une annotation vide (aucune réponse, aucun span, aucune paire) n'est pas enregistrée.

## 4. Permissions

Un service `DatasetAccess`, qui répond à ces questions à partir de l'`Actor`:

| Action | Qui |
|---|---|
| Lire un dataset public | tout utilisateur connecté |
| Lire un dataset privé | propriétaire, membres, admin |
| Créer un dataset | tout utilisateur connecté (dans son espace de noms ou celui d'une organisation dont il est membre) |
| Modifier / supprimer un dataset, gérer les membres | propriétaire, `maintainer`, admin |
| Créer une tâche d'annotation | quiconque peut lire le dataset |
| Annoter | quiconque peut lire le dataset (ses propres annotations uniquement) |
| Modifier les labels, fermer ou supprimer une tâche | créateur de la tâche, maintainer du dataset, admin |
| Lire les annotations des autres | créateur de la tâche, maintainer, admin (les autres ne voient que les leurs) |

Le dernier point est une proposition: elle évite que les annotateurs se copient entre eux. À confirmer (voir **11**).

## 5. API

Préfixe `/api`. Toutes les routes exigent d'être connecté. Les listes sont paginées par curseur.

**Datasets**
- `GET /datasets?q=&modality=&sort=downloads|likes|updated&cursor=` : la liste (recherche, filtre par modalité, tri).
- `POST /datasets` : crée (métadonnées seulement).
- `GET /datasets/{owner}/{name}` : le détail et la dernière version.
- `PATCH /datasets/{owner}/{name}` · `DELETE /datasets/{owner}/{name}`
- `PUT /datasets/{owner}/{name}/like` · `DELETE …/like`
- `GET /datasets/{owner}/{name}/members` · `PUT/DELETE …/members/{user_id}`

**Fichiers et versions**
- `POST /datasets/{owner}/{name}/uploads` : démarre un dépôt et renvoie des URLs présignées (voir **6**).
- `POST /datasets/{owner}/{name}/uploads/{id}/complete` : crée la nouvelle version.
- `GET /datasets/{owner}/{name}/files` : les fichiers de la dernière version.
- `GET /datasets/{owner}/{name}/files/{path}` : redirection vers une URL présignée de téléchargement (compte un téléchargement).

**Aperçu (« viewer »)**
- `GET /datasets/{owner}/{name}/rows?split=train&offset=0&limit=5&q=` : des lignes, au format `{ columns, rows, total }`.
  Le champ `q` filtre le texte dans le split (recherche du viewer). Limite haute sur `limit` (100).

**Tâches d'annotation**
- `GET /datasets/{owner}/{name}/tasks` : les tâches du dataset, avec progression (`my_done`, `total_done`, `annotators`).
- `POST …/tasks` : crée une tâche, avec ses labels.
- `GET /tasks/{id}` · `PATCH /tasks/{id}` (nom, statut)
- `PUT /tasks/{id}/labels` : remplace la liste des labels. **Les labels existants sont reconnus par leur `id`**: absent
  de la liste = supprimé logiquement; `id` inconnu = nouveau label; `id` connu = mise à jour. Une réponse
  `usage` indique combien d'annotations utilisent chaque label (le frontend l'affiche).

**Annotations**
- `GET /tasks/{id}/rows?cursor=&only=todo|mine` : les lignes à annoter, avec **mon** annotation si elle existe.
  Sert l'espace d'annotation (une ligne à la fois, saut vers n'importe quelle ligne).
- `PUT /tasks/{id}/rows/{split}/{row_index}/annotation` : crée ou remplace **mon** annotation de cette ligne
  (idempotent). Le corps dépend du type de tâche (voir **5.1**).
- `DELETE …/annotation` : retire mon annotation.
- `GET /tasks/{id}/progress` : compteurs.
- Plus tard: `GET /tasks/{id}/annotations` (celles des autres, pour la revue), `POST /tasks/{id}/export`.

### 5.1 Corps d'une annotation

Les trois formes correspondent à `Answer` dans [`frontend/src/features/datasets/annotation/store.ts`](../frontend/src/features/datasets/annotation/store.ts).

```jsonc
// classification
{ "label_id": "…", "reason": "texte libre, facultatif" }

// ner
{ "spans": [
    { "label_id": "…", "start": 12, "end": 24, "value": "2023-03-12", "reason": "…" }
  ] }

// qa
{ "pairs": [
    { "question": "…", "answer": "…",
      "answer_span": { "start": 40, "end": 52 },        // null si tapée à la main
      "sources": [ { "start": 0, "end": 80 } ],
      "reason": null }
  ] }
```

Le serveur remplit `text` (copie du passage) à partir du texte de la ligne, il ne fait pas confiance au client.
Il vérifie que `0 ≤ start < end ≤ len(texte)`.

## 6. Stockage des fichiers

- Un seul bucket (`AWS_BUCKET`), clés de la forme `datasets/{dataset_id}/{version_number}/{path}`.
- **Dépôt**: le client envoie directement vers S3 avec des URLs présignées (multipart au-delà de ~100 Mo), pour ne pas
  faire transiter les gros fichiers par l'API. À la fin, `complete` vérifie la taille et le `sha256`, puis crée la
  version.
- **Téléchargement**: URLs présignées de courte durée, jamais de fichier relayé par l'API.
- Les tailles réelles vont de quelques ko à plusieurs dizaines de Go (audio, vidéo): prévoir des limites
  configurables dans `config.py`.
- **Aperçu**: le viewer ne lit jamais tout un fichier. Pour Parquet, on lit seulement les groupes de lignes
  nécessaires (`pyarrow`); pour CSV et JSONL, on lit les premiers Mo. Le résultat des premières lignes est mis en
  cache en base (`dataset_versions.preview` en JSON) à la création de la version.

## 7. Export des annotations

Un projet d'annotation validé produit une **nouvelle configuration** du dataset (comme les `configs` de
Hugging Face), par exemple `movie-reviews-fr` → config `sentiment`:

- Un export est une tâche de fond: il lit les annotations `submitted`, écrit un fichier Parquet ou JSONL
  `datasets/{id}/{version}/configs/{task_name}/…` et l'ajoute à la version.
- Règle de résolution entre annotateurs: à décider (voir **11**). Pour la première version, exporter toutes les
  annotations avec leur `annotator`, sans trancher.

## 8. Ordre de construction proposé

1. **Datasets sans fichiers**: tables `datasets`, `dataset_members`, `dataset_likes`; routes de liste, détail, création,
   suppression, like; `DatasetAccess`; migration; tests. Le frontend remplace `mockData.ts` par ces appels.
2. **Fichiers et versions**: URLs présignées, `dataset_versions`, `dataset_files`, `dataset_splits`, téléchargement.
3. **Aperçu**: route `rows`, lecture Parquet/CSV/JSONL, cache d'aperçu. Le frontend remplace `sample` des viewers.
4. **Tâches de classification**: `annotation_tasks`, `annotation_labels`, `annotations`, routes de tâches et
   d'annotation. C'est la plus simple et elle fixe les routes, les permissions et la progression.
5. **Extraction d'entités**: `annotation_spans`, validation des formats, chevauchements.
6. **Question-réponse**: `qa_pairs`, `qa_sources`.
7. **Export** vers une nouvelle configuration.
8. **Plus tard**: pré-annotation, revue et accord entre annotateurs, annotation des autres modalités.

Chaque étape se termine par une migration, des tests et la mise à jour de `docs/data-model.*` (le schéma est généré
avec `eralchemy`/`graphviz`, voir `backend/scripts`).

## 9. Ce que le frontend mocke aujourd'hui

| Fichier du frontend | Contenu mocké | Remplacé par |
|---|---|---|
| `features/datasets/mockData.ts` | `DATASETS`, `getDataset`, `Dataset.sample`, `series` | routes de **5** (datasets, rows) |
| `features/datasets/annotation/store.ts` | projets, labels, réponses, `CURRENT_USER`, `saveAnswer`, `updateLabels`, `addProject` | routes de tâches et d'annotation, via react-query (déjà installé) |
| `annotation/AnnotationWorkspace.tsx` | `rows = d.sample`, progression locale | `GET /tasks/{id}/rows` |
| `annotation/AnnotationTab.tsx` | progression inventée (`done`, `annotators`) | `GET …/tasks` |
| `annotation/format.ts` | validation des formats, côté client | **garder** (retour immédiat), et valider aussi côté serveur |
| `components/viewers/*` | images, audio et vidéo générés | URLs présignées de **6** |

Conversions à faire dans le client au moment du branchement:
- **Mots → caractères**: aujourd'hui les spans sont des indices de mots (`start`/`end` inclus); l'API attend des
  offsets en caractères (fin exclue).
- **`CURRENT_USER`** devient l'utilisateur de `AuthProvider` (`useCurrentUser`).
- Les `id` de labels générés côté client (`newLabel()`) deviennent des UUID fournis par le serveur; une tâche en création
  envoie les labels sans `id` et reçoit les `id` en retour.

## 10. Non-fonctionnel

- **Volumétrie**: la liste d'un dataset de 100 000 lignes à annoter ne doit jamais être chargée en entier; tout passe
  par curseur et `limit`. Index sur `annotations(task_id, annotator)` et `annotations(task_id, row_index)`.
- **Concurrence**: deux annotateurs sur la même ligne n'entrent pas en conflit (une annotation chacun).
  La contrainte unique `(task_id, split, row_index, annotator)` + `PUT` idempotent règle le double-clic.
- **Sécurité**: aucune URL présignée n'est loguée; l'accès à un dataset privé est vérifié à chaque route, y compris
  les routes de tâche (qui remontent au dataset). Pas de HTML dans les noms ni les descriptions (échappement côté
  affichage, longueur maximale côté schema).
- **Suppression**: supprimer un dataset supprime ses tâches et annotations (cascade) et programme la suppression des
  fichiers S3. Demander une confirmation côté interface.
- **Observabilité**: journaliser créations, suppressions et exports avec l'`user_id`, jamais le contenu annoté.

## 11. Questions ouvertes

1. **Visibilité des annotations des autres.** Un annotateur voit-il ce que les autres ont répondu sur une ligne?
   Proposition: non, seul le créateur et les maintainers.
2. **Espaces de noms.** `owner` est-il uniquement l'utilisateur, ou aussi des organisations? Si oui, d'où viennent-elles
   (groupes Keycloak via `OIDC_GROUPS_CLAIM`, ou table à nous)?
3. **Accès à un dataset privé.** Par invitation nominative, par groupe Keycloak, ou les deux?
4. **Plusieurs annotateurs sur une ligne.** Combien au minimum avant de la considérer faite? Comment résoudre les
   désaccords à l'export (vote majoritaire, revue, tout garder)?
5. **Quota et taille maximale** d'un dataset, d'un fichier, d'un compte.
6. **Licence et contenu.** Faut-il valider ou modérer ce que les gens déposent?
7. **Lignes modifiées entre deux versions.** On marque `stale` (proposé); faut-il aussi proposer de migrer les
   annotations vers la nouvelle version quand le hash correspond encore?
8. **Classification multi-label** et **annotation partielle** (annoter seulement un sous-ensemble): à prévoir dès
   la table `annotation_tasks`, ou à ajouter plus tard?
9. **Annotation des autres modalités**: mêmes tables avec un type de tâche en plus (boîtes englobantes, segments
   audio), ou tables dédiées?
