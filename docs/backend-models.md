# Les modèles: tables

Le même découpage que les datasets (`datasets`, `dataset_members`, `dataset_versions`, `dataset_files`), pour que les deux
espaces se comportent pareil. Ce document décrit les **tables** (issue #14); les routes, le client MLflow et le reste
viennent ensuite (voir l'épique #21 et [mlflow.md](mlflow.md)).

Un modèle est **un artefact, une référence de code, ou les deux**. Les poids seuls peuvent suffire (une architecture
standard, ou un modèle déjà packagé pour MLflow); sinon une version pointe vers le code qui les fait tourner (GitHub ou
GitLab). **La plateforme ne clone ni n'exécute jamais ce code**: elle garde un lien.

| Table | Contient |
|---|---|
| `models` | le modèle: adresse `owner/name` (unique), description, `tasks` et `inputs` (jamais changés après la création), bibliothèque, langues, licence, tags, visibilité, fiche (markdown), lien `code_url` (la maison du code, pour la page), nombre de paramètres, jeux d'entraînement (`owner/name`, dits par l'auteur), compteurs, `version` et `size_bytes` de la dernière version |
| `model_members` | les accès en plus du créateur: `reader` ou `maintainer` |
| `model_likes` | un « j'aime » par personne |
| `model_versions` | un instantané: numéro, état, référence MLflow, référence de code |
| `model_files` | les fichiers d'une version (chemin, taille, empreinte, clé de stockage) |

## Ce qu'il faut savoir

- **Le propriétaire et les admins de la plateforme ne sont pas des membres**: ils se déduisent (créateur du modèle, ou
  `is_admin`), comme pour les datasets. Les rôles stockés sont donc `reader` et `maintainer` (il n'y a pas d'`annotator`:
  l'annotation est une affaire de dataset). Éditent: le propriétaire, les admins, les mainteneurs.
- **`tasks` et `inputs`** (les types de tâches d'annotation que le modèle sait faire, les types de données qu'il prend) sont
  des listes, comme dans le frontend. `inputs` est borné aux modalités des datasets par une contrainte; `tasks` ne l'est pas
  en base (la liste des tâches évolue): c'est l'API qui la validera. Ils ne changent plus après la création, ce que fera
  respecter le service.
- **Une version pointe vers MLflow** par `mlflow_name` et `mlflow_version` (les deux ou aucun: une version qui n'est que du code
  n'en a pas), plus `mlflow_run_id` si on le connaît. Une version de MLflow n'appartient qu'à une version d'ici (index unique
  partiel). `servable` dit si MLflow peut la servir.
- **Le code d'une version** est un lien validé par le service (https, hôtes autorisés), jamais lu depuis ici:
  `code_url`, `code_ref` (ce que l'auteur a écrit, tel quel), `code_ref_kind` (`commit`, `tag`, `branch`, `unknown`),
  `code_path`, `entrypoint`, et ce que le worker en tire (#27): `code_sha`, `code_state`, `code_error`.

| `code_state` | Veut dire |
|---|---|
| `none` | pas de code (et alors `code_url` est vide) |
| `unresolved` | un lien, pas encore regardé par le worker |
| `resolving` | le worker s'en occupe |
| `pinned` | résolu en un commit, `code_sha` (jamais changé ensuite: une version est un instantané) |
| `unverified` | introuvable ou privé: le lien est gardé tel qu'écrit |
| `failed` | la résolution a échoué (`code_error` dit pourquoi) |

Les règles sont **dans la base** (contraintes écrites à la main, que l'autogénération n'écrit pas): valeurs des états,
`code_state = 'none'` exactement quand `code_url` est vide, `code_sha` renseigné exactement quand l'état est `pinned`, un
commit fait 40 (SHA-1) ou 64 (SHA-256) caractères hexadécimaux en minuscules, compteurs positifs, numéro de version à partir
de 1.
- **Qu'une version ait au moins un artefact ou un lien de code** n'est pas une contrainte de la base (les fichiers sont dans
  une autre table): c'est le service qui crée la version qui le vérifie (#17).
- **Un fichier gardé d'une version à la suivante garde sa clé de stockage** (stocké une fois), comme pour les datasets. Le
  ramasse-miettes (section 6 quater de [backend-datasets.md](backend-datasets.md)) ne parcourt pas encore les clés des
  fichiers de modèles: il faudra les ajouter à ses références avant de les stocker (#17).
- Supprimer un modèle supprime en cascade ses membres, ses « j'aime », ses versions et leurs fichiers.
- Les index partiels pour le worker: versions en attente, et versions dont le code reste à résoudre.

## Les routes (issue #16)

Même découpage que les datasets: `routers/models.py` → `ModelService` / `ModelMemberService` → `ModelRepository`, les droits
dans `ModelAccess` (comme `DatasetAccess`). Les erreurs sont traduites dans `routers/errors.py`.

| Route | Rôle |
|---|---|
| `GET /api/models` | la liste (`Page`): filtres `q`, `owner`, `task`, `modality` (un des `inputs`), `library`, `language`, `license`, `tags` (tous), tri `downloads`, `likes` ou `updated` |
| `POST /api/models` | créer, dans son propre espace de noms |
| `GET / PATCH / DELETE /api/models/{owner}/{name}` | lire, modifier, supprimer |
| `PUT / DELETE …/like` | « j'aime » (le refaire ne change rien) |
| `GET …/members`, `PUT / DELETE …/members/{user_id}` | qui a accès en plus du créateur (`reader` ou `maintainer`) |

`tasks` et `inputs` se choisissent à la création et ne changent plus (`PATCH` refuse tout champ inconnu: `name`, `owner`,
`tasks`, `inputs` donnent 422). `code_url` et `parameters` peuvent être remis à `null`; les autres champs envoyés ne le
peuvent pas.

### Permissions

| Action | Qui |
|---|---|
| Lire un modèle public, l'aimer | tout utilisateur connecté |
| Lire un modèle privé, l'aimer | créateur, membres (`reader`, `maintainer`), admin |
| Créer un modèle | tout utilisateur connecté (dans son espace de noms) |
| Modifier, supprimer, gérer les membres, voir le lien MLflow | créateur, `maintainer`, admin |

Un modèle privé qu'on ne peut pas voir répond **404** à toutes les routes (jamais 403): impossible de savoir s'il existe. Un
lecteur d'un modèle qu'il voit reçoit **403** pour ce qu'il n'a pas le droit de faire. Les membres ne sont visibles que de
ceux qui peuvent éditer; ils sont désignés par leur `sub` (il n'y a pas de table des utilisateurs). Le créateur n'est jamais
membre (422).

### Le lien vers MLflow

`mlflow_url` est dans la réponse **uniquement** pour ceux qui peuvent éditer le modèle, **si** `MLFLOW_PUBLIC_URL` est
renseigné **et** que MLflow connaît déjà quelque chose du modèle (une version qui y pointe). Pour tous les autres la clé est
**absente** (pas `null`). L'adresse interne (`MLFLOW_TRACKING_URI`) n'apparaît jamais. Le lien de chaque version viendra avec
les routes des versions (#17), construit par le même `MlflowLinks`.

### MLflow et la base

- **Créer** un modèle n'appelle pas MLflow: il y apparaît avec sa première version (#17). On peut donc créer, lister et
  lire pendant une panne de MLflow.
- **Supprimer**: MLflow d'abord, la base ensuite (règle de [mlflow.md](mlflow.md)). Si MLflow ne répond pas, rien n'est
  supprimé (503) et on peut recommencer: supprimer dans MLflow ne fait rien pour ce qui n'existe plus. Un modèle que MLflow ne
  connaît pas ne l'appelle pas. Les fichiers du stockage partent une fois le modèle vraiment supprimé. Les artefacts que MLflow
  laisse dans le seau sous `mlflow/` restent (limite connue, voir [mlflow.md](mlflow.md)).
- `code_url` doit être en `https` sur un hôte de `MODEL_CODE_HOSTS` (`github.com`, `gitlab.com` par défaut), sans identifiants
  dans l'adresse. Elle n'est jamais lue.
