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

## Les versions et l'envoi des fichiers (issue #17)

### Où sont les fichiers, et ce que MLflow en voit

**Les poids restent dans notre stockage**, sous `models/{model_id}/files/{file_id}`: une clé par fichier envoyé, partagée
par les versions qui le gardent (un fichier qui ne change pas d'une version à la suivante est stocké **une fois**). MLflow
ne reçoit **qu'un manifeste** (`MANIFEST.json`: chemins, tailles, empreintes, lien vers le code) dans un run, et la version
enregistrée est ce run. Pourquoi: MLflow n'enregistre une version que si ses fichiers sont dans les artefacts d'un run, ce
qui obligerait à recopier chaque version entière et ferait perdre la déduplication. Les versions, les alias et l'interface
de MLflow marchent; une copie complète pour **servir** un modèle ne sera faite qu'à la demande (#18). `servable` reste faux
d'ici là.

Un modèle n'existe dans MLflow qu'à sa première version avec des fichiers. Une version qui n'est que du code n'y est pas.

### Routes

| Route | Rôle |
|---|---|
| `POST /api/models/{o}/{n}/uploads` | annonce les fichiers (`files`, `remove`, `message`, `code`): les parties partent directement vers le stockage |
| `GET /api/model-uploads/{id}` (`?parts=true`) | l'état, et ce qui est arrivé (pour reprendre) |
| `POST /api/model-uploads/{id}/parts` | adresses signées des parties |
| `POST /api/model-uploads/{id}/complete` | assemble, crée la version, l'enregistre dans MLflow (rejouer rend la même version) |
| `DELETE /api/model-uploads/{id}` | abandonner |
| `POST /api/models/{o}/{n}/versions` | une version qui n'est qu'un lien vers le code (aucun envoi) |
| `GET …/versions`, `GET / DELETE …/versions/{number}` | historique, détail avec ses fichiers, suppression |
| `GET …/files`, `GET …/files/{path}` | les fichiers d'une version; le second redirige (302) vers une adresse signée et compte un téléchargement |

Seuls les éditeurs envoient et suppriment; tout lecteur du modèle liste et télécharge; un modèle privé est invisible (404).
`mlflow_url` d'une version suit la même règle que celui du modèle: éditeurs seulement, clé absente sinon.

### Ordre des appels

`complete`: les parties sont vérifiées (toutes là, bonne taille), assemblées, puis **MLflow d'abord** (modèle enregistré si
besoin, run, manifeste, version), **la base en dernier**. Si MLflow ne répond pas, ou si la base échoue, ce qui a été fait
dans MLflow est défait, les objets assemblés sont supprimés, les parties non assemblées sont abandonnées et l'envoi est
terminé (`aborted`): il faut le refaire. Un modèle enregistré qui avait déjà des versions n'est jamais supprimé par cette
défausse. Les numéros se suivent: une version à la fois par modèle (verrou sur la ligne du modèle).
Supprimer une version: MLflow d'abord (503 si muet, on peut recommencer), puis la base, puis les objets que **aucune autre
version** ne garde. `model.version` et `size_bytes` suivent la dernière version restante.

### Le code d'une version

Une version est **des fichiers, un lien vers le code, ou les deux**; ni l'un ni l'autre: 422. Le code est écrit **sur la
version** et n'est pas hérité de la précédente. Règles (`services/code_reference.py`), vérifiées avant tout envoi: `https`
seulement, pas d'identifiants, hôte de `MODEL_CODE_HOSTS` (donc ni IP ni nom interne), port par défaut, chemin exactement
`/{owner}/{dépôt}` (pas de `..`, de requête ni de fragment), `ref` sans `..`, `path` et `entrypoint` relatifs. Un commit
(40 ou 64 caractères hexadécimaux) est reconnu; une branche et un tag ne se distinguent pas (`unknown`). L'adresse est gardée
**telle qu'écrite**, en état `unresolved`; le worker l'épinglera à un commit (#27), et ce commit ne change plus. **L'API ne
lit ni ne clone jamais** cette adresse.

### Pourquoi `model_uploads` et pas une généralisation de `dataset_uploads`

Même contrat, mais ce qui entoure l'envoi diffère (ici l'enregistrement dans MLflow et le lien vers le code, là le README et
la lecture des lignes): un service commun aurait une condition par cas dans chaque méthode. Le service est donc une copie
adaptée, et ce qui est vraiment commun est importé (`part_size_for`, `PlannedFile`, `clean_path` déplacé dans
`services/paths.py`). L'expiration des envois abandonnés passe par la même route interne que les datasets
(`POST /api/internal/dataset-uploads/expire` expire aussi ceux des modèles).

### Ramasse-miettes

Il connaît maintenant `models/`: une clé que pointe un `model_files`, ou un envoi de modèle encore ouvert, n'est pas du
déchet; un envoi en parties que possède un envoi ouvert de modèle n'est pas abandonné; l'échantillon de vérification inclut
les fichiers de modèles. Ce que MLflow garde sous `mlflow/` (manifestes, anciens runs) reste hors de sa portée.

### Limites

`MODEL_FILE_MAX_BYTES` (50 Gio), `MODEL_VERSION_MAX_FILES` (500), les parties et la durée d'une session comme les datasets.

### La vérification des fichiers par le worker

Un fichier envoyé en parties n'a pas d'empreinte: la version est `pending` et `POST /api/internal/model-versions/{id}/…`
(`claim`, `result`, `failure`, `release`, `waiting`, même schéma que pour les datasets) laisse le worker la vérifier. La tâche
`models.process_version` (même file `datasets`) télécharge chaque fichier **sans le garder** (on ne lit rien dedans: un
poids peut faire des dizaines de Gio) et renvoie sa taille et son sha256. L'API:

- compare la taille à celle annoncée, et l'empreinte à celle que le navigateur avait annoncée: un écart met la version en
  `failed` avec **le fichier nommé** dans `error`, sans rien garder des empreintes écrites; une version `failed` ne se
  télécharge pas (409) et peut être revérifiée;
- écrit les empreintes, et si le même contenu est déjà dans le modèle sous une autre clé, fait pointer le fichier vers
  l'objet existant et supprime le doublon (**un contenu n'est stocké qu'une fois**);
- passe la version à `ready`.

Reprise: un worker mort est remplacé au bout de `PROCESSING_STALE_MINUTES`, le balayage (`datasets.process_waiting`) remet en
file les versions oubliées, trois essais au plus. Le manifeste donné à MLflow garde les empreintes inconnues au moment de la
création (`null`): c'est la base de la plateforme qui fait foi. Un fichier dont l'empreinte est connue n'est plus renvoyé
(`already_stored`), et une version dont tous les fichiers sont connus est `ready` d'emblée.

### Vérifié à la main

Un fichier de 300 Mio (5 parties de 64 Mio) contre le vrai compose (RustFS, MLflow, worker): envoi en 7 s, version `ready`
après la vérification du worker, empreinte égale à celle calculée à l'envoi, téléchargement par adresse signée identique,
version et lien MLflow présents, puis suppression du modèle (MLflow et stockage).

## Épingler le code d'une version (issue #27)

### Les trois cas

| Cas | Ce que la version a | `code_state` |
|---|---|---|
| **Artefact seul** (une architecture standard, un modèle déjà emballé pour MLflow) | des fichiers, pas de lien | `none` |
| **Artefact + code** (le cas courant d'un modèle qui a besoin de code) | des fichiers et un lien | `unresolved`, puis l'un des états ci-dessous |
| **Code seul** | un lien, pas de fichier à soi | idem; la version est `ready` d'emblée |

Le code est écrit **sur la version** (un état du code va avec un jeu de poids) et n'est pas hérité de la précédente. Une
version a au moins l'un des deux, sinon 422.

### Ce que veut dire « épinglé »

Une branche et un tag bougent; un commit non. L'auteur écrit ce qu'il veut (`ref`: un commit, un tag, une branche, ou rien =
la branche par défaut), la plateforme le garde **tel quel** et le worker cherche **le commit** vers lequel ça pointe:

| `code_state` | Veut dire |
|---|---|
| `unresolved` | pas encore regardé: la page dit « non épinglé » |
| `resolving` | un worker s'en occupe |
| `pinned` | le commit est dans `code_sha` (40 ou 64 caractères hexadécimaux, minuscules) et **ne change plus jamais**: un autre commit est une autre version. `tree_url` donne la page de l'arbre à ce commit (et au dossier `path`), construite par la plateforme |
| `unverified` | dépôt ou référence introuvable, ou dépôt privé: le lien reste tel qu'écrit, `code_error` dit pourquoi. **Ce n'est pas un échec de la version** |
| `failed` | l'hôte a répondu quelque chose d'inutilisable, ou le travail a été interrompu trop de fois (`code_error`) |

Un dépôt privé n'est jamais résolu et aucun identifiant n'est demandé ni gardé. Un dépôt peut disparaître ou être réécrit
après coup: le commit reste dans la fiche, le lien peut casser, et la page doit le dire plutôt que le cacher.

### Les règles de l'adresse

Vérifiées par l'API avant tout (`services/code_reference.py`) **et revérifiées par le worker** avant d'appeler quoi que ce
soit (`worker/code.py`): `https` seulement, pas d'identifiants, hôte de la liste (`MODEL_CODE_HOSTS` côté API, `CODE_HOSTS`
côté worker; une entrée `hôte:port` autorise ce port, sinon 443), donc ni IP, ni `localhost`, ni nom terminé par un point;
chemin `/{propriétaire}/{dépôt}` (GitHub), ou avec des groupes dans des groupes pour un GitLab (6 niveaux au plus); pas de
`..`, `//`, requête ni fragment; un segment ne commence pas par `-` (c'est le marqueur des pages de GitLab). `code_path` et
`entrypoint` sont relatifs, sans `..`.

### Ce que fait le worker

La tâche `models.resolve_code` (file `datasets`, 30 appels par minute et par worker) demande **seulement** le commit:
GitHub `GET api.github.com/repos/{o}/{r}/commits/{ref}`, GitLab `GET /api/v4/projects/{chemin}/repository/commits/{ref}`
(`HEAD` quand il n'y a pas de référence). Rien n'est cloné ni téléchargé. L'adresse appelée est **reconstruite** à partir
des parties vérifiées, jamais prise telle qu'elle a été envoyée.

| Réponse | Résultat |
|---|---|
| 200 | `pinned` (si la référence était un commit, la réponse doit être le même) |
| 404, 422, 401, 403 simple | `unverified` |
| 429, ou 403 avec limite atteinte | l'API reprend la main (`release`), nouvel essai après le délai que l'hôte donne, sinon un délai croissant (8 essais) |
| 5xx, réseau, nom introuvable | idem, délai croissant |
| autre, corps illisible, trop gros | `failed` avec la raison |

Protections contre le SSRF (l'adresse vient des utilisateurs): liste d'hôtes; **aucune redirection suivie** hors du même hôte
(même schéma, même port: un 302 vers `http://169.254.169.254` n'est jamais suivi); hôte qui se résout vers une adresse privée
(boucle locale, `169.254.x.x`, réseaux privés…) **refusé avant de se connecter**, sauf s'il est nommé dans
`CODE_PRIVATE_HOSTS` (un GitLab dans le réseau de l'entreprise); délai court (`CODE_TIMEOUT_SECONDS`); réponse limitée
(`CODE_MAX_ANSWER_BYTES`, par l'en-tête puis en lisant). Limite connue: le nom est résolu pour la vérification puis résolu
encore par la connexion; un attaquant qui contrôle le DNS d'un hôte de la liste pourrait changer la réponse entre les deux.
Les hôtes de la liste sont des services publics connus, et le worker n'a ni base de données ni clé du stockage: c'est
acceptable, mais à savoir si on ajoute un hôte qu'on ne contrôle pas.

Jetons: `CODE_TOKENS` (JSON, `{"github.com": "…"}`) relève la limite de débit des recherches publiques. Un jeton ne part que
vers son hôte (jamais vers la cible d'une redirection, qui est de toute façon refusée), et n'est écrit dans aucun journal ni
message d'erreur.

### Reprise

Le code d'une version a ses propres compteurs (`code_attempts`, `code_started_at`), distincts de ceux de la vérification des
fichiers: les deux travaux sont indépendants. Un worker mort est remplacé au bout de `PROCESSING_STALE_MINUTES`, le balayage
remet en file le code oublié (`GET /api/internal/model-code/waiting`), trois prises au plus. Le travail est mis en file par
nom (`models.resolve_code`) quand la version est enregistrée.

### Pas fait ici

La licence et la branche par défaut du dépôt, que l'issue mentionne comme « informatives », ne sont pas gardées: aucune colonne
ne les attend et rien ne s'en sert pour l'instant.
