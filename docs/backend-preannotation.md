# Backend de la pré-annotation

Complète [backend-datasets.md](backend-datasets.md), [backend-tabular-annotation.md](backend-tabular-annotation.md),
[backend-timed-media.md](backend-timed-media.md) et [image-annotation-ideas.md](image-annotation-ideas.md). Les conventions
de ces documents s'appliquent (couches, `Actor`, UUID, Alembic, pas de table `users`, formes de réponse par type de tâche).

Une **pré-annotation** est un traitement où un **modèle** propose une réponse pour chaque élément d'une tâche. Un humain
doit **valider, corriger ou rejeter** chaque proposition: tant qu'il ne l'a pas fait, la proposition ne compte pour rien.
Ce que les humains décident est conservé: c'est ce qui permet de savoir quel modèle utiliser ensuite.

## 1. Ce que le frontend fait aujourd'hui (avec des données simulées)

| Besoin | Où dans le frontend |
|---|---|
| Lancer, suivre, arrêter, reprendre, supprimer un traitement | `PreannotationDialog.tsx`, `runs.ts` |
| Les modèles proposés selon le type de tâche | `models.ts` (`modelsFor`) |
| Voir et valider une proposition dans l'espace d'annotation | `ProposalBanner.tsx` et les espaces de travail |
| Enregistrer ce qui a été décidé | `store.ts` (`commitAnswer`, `rejectProposal`, `Decision`, `statsOf`) |
| Comparer les modèles | `PreannotationDialog.tsx` (tableau « Quel modèle choisir ? ») |
| Produire des propositions | `preannotate.ts` (`makeProposal`): **simulation**, à remplacer par un vrai appel de modèle |

Règles déjà en place dans l'interface, que le backend doit garantir:
- Une proposition n'est **jamais** une réponse: elle n'entre ni dans la progression, ni dans l'accord entre annotateurs,
  ni dans les exports tant qu'un humain ne l'a pas validée.
- Le modèle est choisi parmi ceux **compatibles avec le type de tâche** (pas de détecteur d'objets sur du texte).
- Supprimer un traitement retire les propositions pas encore décidées; **les réponses validées et les statistiques restent**.
- Une réponse garde sa **provenance**: `human`, `model` (proposition validée telle quelle) ou `model_edited`.

## 2. Principes

1. **Une couche à part.** Les propositions vivent dans leurs tables, pas dans `annotations`. Une réponse n'est créée que
   par un humain.
2. **Les décisions sont immuables.** Elles ne sont jamais modifiées ni supprimées avec le traitement (voir **8** pour la
   durée de conservation).
3. **Le serveur recalcule ce qui compte.** Le client dit « j'ai validé cette proposition »; c'est le serveur qui compare la
   réponse à la proposition et déduit « telle quelle » ou « modifiée ». On ne fait pas confiance au client pour les
   statistiques.
4. **Un modèle ne voit que ce qu'on lui donne.** Il lit les éléments par URL présignée de courte durée et ne reçoit jamais
   les réponses des humains.
5. **Les erreurs d'un modèle ne bloquent pas les humains.** Un traitement qui échoue laisse intactes les propositions déjà
   faites et les annotations.

## 3. Modèle de données

### 3.1 Les modèles

**`models`**: le catalogue des modèles utilisables.
- `id` (UUID), `name` (ex. `ner-legal`), `description`, `owner`, `status` (`active` | `deprecated` | `disabled`).
- `task_types` (tableau): les types de tâche qu'il sait faire (`ner`, `image_detection`, `audio_transcription`…).
  C'est ce qui fait que le menu n'affiche que les modèles compatibles.
- `modalities` (tableau): les types de données (texte, image, son…), redondant avec les types de tâche mais utile pour filtrer.
- `provider` (`internal` | `http` | `external_api`), `endpoint`, `config` (JSONB, sans secret), `secret_ref` (référence à un
  coffre, jamais la valeur), `timeout_s`, `max_batch`, `cost_per_item` (nullable).
- `external` (bool) et `data_policy`: indique si les données quittent l'infrastructure (voir **7**).

**`model_versions`**: `id`, `model_id`, `version` (`2.1.0`), `released_at`, `changelog`, `status`. **Les statistiques
se rattachent à une version**, pas au nom du modèle: une version corrigée ne doit pas hériter du score de la précédente.

### 3.2 Les traitements

**`preannotation_runs`**
- `id`, `task_id`, `model_version_id`, `dataset_version_id` (la version du dataset est **figée** au lancement).
- `status`: `queued` | `running` | `stopped` | `done` | `failed` | `deleted`.
- `total` (éléments à traiter, fixé au lancement), `processed`, `succeeded`, `failed_items`.
- `selection` (JSONB): quels éléments (voir **4.2**). `params` (JSONB): réglages envoyés au modèle.
- `started_by`, `started_by_username`, `created_at`, `started_at`, `ended_at`, `error` (dernier message d'échec).
- `cost` (estimé puis réel), `deleted_at`.
- Index sur `(task_id, status)`.

**`preannotation_run_items`**: la file de travail. `(run_id, item_ref)` unique, `position`, `status` (`todo` | `done` |
`failed` | `skipped`), `attempts`, `error`. Elle permet l'arrêt, la reprise et les nouvelles tentatives sans recalculer
la sélection.

### 3.3 Les propositions

**`proposals`**
- `id`, `run_id`, `task_id`, `item_ref` (comme pour les annotations: split et ligne, identifiant de série, clip…),
  `model_version_id`.
- `payload` (JSONB): **la même forme qu'une réponse de ce type de tâche** (voir les corps de `PUT …/annotation` des autres
  documents). Ainsi le frontend préremplit le formulaire avec la proposition sans conversion.
- `confidence` (0 à 1, nullable) pour l'élément entier, et, dans `payload`, une confiance **par objet** quand le modèle en
  donne une (par boîte, par entité, par région): voir **10**.
- `status`: `active` | `superseded` | `deleted`.
- `created_at`. Unique `(task_id, item_ref)` parmi les propositions `active`: **un élément n'a qu'une proposition active**;
  une nouvelle proposition d'un autre traitement passe l'ancienne à `superseded`.

**`proposal_decisions`**: **une ligne par annotateur et par proposition**, jamais modifiée.
- `id`, `proposal_id`, `run_id`, `task_id`, `annotator` (`sub`), `outcome` (`accepted` | `edited` | `rejected`),
  `annotation_id` (la réponse produite, nulle si rejetée), `at`.
- Copie **dénormalisée** de ce qui sert aux statistiques, pour qu'elles survivent à toute suppression:
  `model_version_id`, `task_type`, `modality`, `language`, `confidence`, `edit_score` (voir **6.2**), `decision_ms`
  (temps passé sur l'élément).
- Unique `(proposal_id, annotator)`.

**`annotations`** (existante): ajouter `origin` (`human` | `model_accepted` | `model_edited`), `proposal_id` et `run_id`
(nullables). C'est la provenance que le frontend affiche déjà (`Answer.origin`, `model`, `run`).

### 3.4 Un écart avec le frontend à corriger

Le frontend simulé retire la proposition **dès que la première personne l'a décidée**. Le modèle réel est différent: une
tâche a **plusieurs annotateurs**, chacun répond de son côté. La proposition reste donc **active pour tous**, et chaque
annotateur a sa propre décision (`proposal_decisions` est par annotateur). Une proposition n'est « à valider » que pour
ceux qui n'ont pas encore décidé. Au branchement, le compteur « à valider » devient **par utilisateur**.

## 4. Cycle de vie d'un traitement

```
queued ─► running ─► done
            │  ▲
        stop│  │resume
            ▼  │
          stopped          running ─► failed
   (tout état) ─► deleted
```

### 4.1 Lancer

`POST /tasks/{id}/preannotations`, qui renvoie `202` et le traitement en `queued`. Le service refuse si:
- le modèle n'est pas compatible avec le type de tâche ou le dataset (422);
- la personne n'a pas le droit (voir **9**);
- un traitement est déjà `queued` ou `running` sur cette tâche (409). Une seule exécution à la fois par tâche (le
  frontend le fait déjà); des limites globales par utilisateur et par jour s'ajoutent (quota).
- le dataset est une version qui n'est pas prête (fichiers en cours de traitement).

Il estime le **coût** et le renvoie avant exécution (`dry_run=true` pour le seul calcul).

### 4.2 Choisir les éléments

`selection.mode`: `unannotated` (défaut, comme le frontend), `all`, ou `sample` (avec `size` et `seed`). Par défaut, un
élément est ignoré s'il a **déjà une réponse humaine**. L'option `overwrite_proposals` (faux par défaut) décide si l'on
remplace les propositions actives d'un autre traitement.

La sélection est calculée **une fois**, au lancement, et stockée dans `preannotation_run_items`: un élément annoté à la
main pendant le traitement est ignoré à l'exécution (comme le fait `runs.ts`).

### 4.3 Exécuter

Un **worker** (file de tâches) traite la file par lots (jusqu'à `model.max_batch`):
1. Lit les éléments (URL présignées), appelle le modèle.
2. Écrit les propositions et fait avancer `processed` **dans la même transaction**: l'opération est **idempotente**
   (unique `(run_id, item_ref)`), donc un lot rejoué après un plantage ne crée pas de doublon.
3. Vérifie à chaque lot que le traitement n'est pas `stopped` ou `deleted`: l'arrêt est **coopératif** (au plus un lot de
   retard).

Un élément en échec est retenté (3 fois, avec attente croissante), puis passe `failed` sans arrêter le traitement.
Le traitement finit `done` si au moins un élément a réussi, `failed` si le modèle est injoignable ou si plus de la moitié
des éléments échouent (seuil configurable).

### 4.4 Arrêter, reprendre, supprimer

- **Arrêter**: `POST …/stop` → `stopped`. Les propositions déjà faites restent utilisables.
- **Reprendre**: `POST …/resume` → `running`, continue la file là où elle s'est arrêtée (même version de dataset).
- **Supprimer**: `DELETE …` → `deleted` (suppression **logique**). Il passe les propositions `active` du traitement à
  `deleted`; **il ne touche ni aux réponses, ni à `proposal_decisions`**. Il demande confirmation côté interface.

### 4.5 Suivre la progression

`GET /preannotations/{id}` renvoie `status`, `total`, `processed`, `failed_items`, les décisions déjà prises
(`accepted`, `edited`, `rejected`) et le nombre de propositions en attente **pour l'utilisateur courant**. Pour éviter
d'interroger toutes les secondes: `GET /preannotations/{id}/events` (Server-Sent Events) qui pousse chaque changement
d'état et de compteur, avec repli sur un sondage toutes les 3 s.

## 5. API

Préfixe `/api`, connecté, pagination par curseur pour les listes.

**Modèles**
- `GET /models?task_type=&modality=` : les modèles compatibles, avec leurs versions.
- `GET /models/{id}` · administration: `POST /models`, `PATCH /models/{id}`, `POST /models/{id}/versions`.

**Traitements**
- `POST /tasks/{id}/preannotations` : `{ model_version_id, selection, params, dry_run }` → `202`.
- `GET /tasks/{id}/preannotations` : l'historique (y compris les supprimés).
- `GET /preannotations/{id}` · `GET /preannotations/{id}/events`
- `POST /preannotations/{id}/stop` · `POST /preannotations/{id}/resume` · `DELETE /preannotations/{id}`

**Côté annotateur**
- `GET /tasks/{id}/rows` : chaque ligne contient, quand l'utilisateur n'a pas encore répondu, sa **proposition active**:
  `{ "proposal": { "id", "model": "ner-legal", "version": "2.1.0", "confidence": 0.82, "payload": { … } } }`.
- `PUT /tasks/{id}/rows/{ref}/annotation` accepte `proposal_id`. Le serveur compare la réponse à `proposal.payload`
  (voir **6.2**), enregistre `origin` et crée la décision dans la même transaction. Les chemins existants (sans proposition)
  ne changent pas.
- `POST /proposals/{id}/reject` : l'annotateur rejette; une décision `rejected` est créée, aucune réponse.
- `POST /proposals/{id}/accept` (raccourci): enregistre la proposition telle quelle comme réponse de l'utilisateur.

**Statistiques**
- `GET /tasks/{id}/preannotations/stats` : par modèle et version, **pour cette tâche**.
- `GET /model-stats?task_type=&modality=&language=` : par modèle et version, sur **toutes les tâches du même type et du
  même type de données** (le frontend a déjà les deux portées « cette tâche » et « tous les … sur … »).
- Le résultat inclut les effectifs, les parts, la confiance, un score (voir **6**) et une indication de fiabilité
  (« pas assez de décisions »).

## 6. Mesures et choix du modèle

### 6.1 Ce qu'on compte

Par modèle (version), type de tâche et type de données:

| Mesure | Définition |
|---|---|
| `decided` | nombre de décisions |
| `accept_rate` | part de propositions validées **telles quelles** |
| `edit_rate`, `reject_rate` | part de propositions corrigées, rejetées |
| `score` | `(acceptées + corrigées / 2) / décidées` (la définition affichée dans l'interface) |
| `mean_edit_score` | **effort de correction moyen** sur les propositions corrigées (voir 6.2) |
| `decision_ms` | temps moyen et médian passé par élément, avec et sans proposition |
| `confidence_acceptees / rejetees` | confiance moyenne du modèle sur ce qui a été accepté puis rejeté |
| `calibration` | taux d'acceptation par tranche de confiance (0–0,1, 0,1–0,2…) |

### 6.2 L'effort de correction

« Corrigée » ne dit pas si c'était un détail ou une réécriture complète. Le serveur calcule un `edit_score` entre 0 (rien
changé) et 1 (tout refait) en comparant la proposition à la réponse, selon le type de tâche:

| Type de réponse | Calcul |
|---|---|
| Label(s), classification | 0 si identique, 1 sinon (ou 1 − Jaccard pour plusieurs labels) |
| Valeur de régression | `|valeur − proposition| / (max − min)` de l'échelle |
| Texte (transcription, description) | distance d'édition normalisée (Levenshtein / longueur) |
| Entités, régions temporelles | 1 − F-mesure des empans appariés par IoU |
| Boîtes, polygones | 1 − IoU moyen des objets appariés (les objets ajoutés ou supprimés comptent 1) |
| Suivi d'objets | 1 − IoU moyen image par image après interpolation (`box_at`) |
| Cellules (tableau) | part de cellules différentes |

Ce calcul est un module (`app/services/proposal_diff.py`) testé avec des **vecteurs partagés**, car il décide de ce que
l'interface affichera comme « corrigée ».

### 6.3 Recommander un modèle

- Un modèle n'est **comparable** qu'avec au moins N décisions (le frontend utilise 10; en production 30 par modèle est
  plus honnête). En dessous, on affiche les chiffres sans classement.
- Le classement s'appuie sur la **borne basse d'un intervalle de confiance** (intervalle de Wilson) du score, pas sur la
  moyenne: 5 décisions parfaites ne battent pas 200 décisions à 90 %.
- La recommandation est donnée **par type de tâche et de données** (et par langue quand elle existe): un modèle excellent
  sur le texte français n'est pas recommandé sur du texte anglais sans mesure.
- **Pas de recommandation automatique silencieuse.** L'interface propose, un humain choisit.

### 6.4 Les biais à connaître

- **Biais d'ancrage.** Un annotateur qui voit une proposition a tendance à l'accepter. Un taux de validation de 95 % peut
  mesurer la fatigue, pas la qualité du modèle. Pour le mesurer, prévoir un **mode « à l'aveugle » sur un échantillon**
  (par exemple 5 % des éléments, tirés au hasard): l'annotateur répond sans voir la proposition, et on compare sa réponse
  à celle du modèle. Les éléments à l'aveugle donnent la **vraie** concordance.
- **Validations de complaisance.** Repérer les annotateurs qui acceptent presque tout en un temps très court
  (`decision_ms` très bas et taux d'acceptation proche de 1). Ne pas les exclure automatiquement: les signaler.
- **Éléments d'or.** Quelques éléments dont la réponse est connue (annotée à la main par un expert) servent à mesurer si
  les annotateurs valident à tort des propositions fausses.
- **Dérive.** Les statistiques se calculent sur une **fenêtre glissante** en plus du total (un modèle peut se dégrader si
  les données changent).

## 7. Intégration des modèles

Une interface unique, indépendante du fournisseur: `POST {endpoint}/predict`, avec pour chaque élément la **même
forme que la réponse attendue** (voir les autres documents), plus un champ `confidence` facultatif.

```jsonc
// requête
{ "task": { "type": "ner", "labels": [ { "id": "…", "name": "PERSONNE", "description": "…", "kind": "entity", "value_type": "text", "formats": [] } ] },
  "items": [ { "ref": "train:12", "url": "https://…presigned…", "text": null } ],
  "params": { } }

// réponse
{ "results": [ { "ref": "train:12", "confidence": 0.82, "payload": { "spans": [ { "label_id": "…", "start": 12, "end": 24 } ] } } ],
  "errors": [ { "ref": "train:13", "message": "…" } ] }
```

- **Les labels de la tâche, avec leurs descriptions, formats et exemples, sont envoyés au modèle** (ce sont des consignes
  pour un modèle généraliste). Le modèle renvoie des `label_id` de la tâche, jamais des noms libres. Le serveur **rejette**
  (et compte comme échec) les labels inconnus.
- Le serveur **valide chaque `payload`** avec les mêmes règles que celles d'une annotation humaine (bornes, labels existants,
  nombre de points…) avant de l'écrire. Une proposition invalide devient un échec d'élément, pas une proposition cassée.
- **Données qui quittent l'infrastructure.** Un modèle `external = true` envoie les éléments à un tiers. Chaque dataset a une
  politique (`allow_external_models`: faux par défaut); le serveur refuse le lancement sinon, et le dialogue le dit.
  Les URL présignées sont de courte durée et jamais journalisées.
- Les **secrets** (clés d'API) ne sont jamais dans `config`: seulement une référence au coffre.
- Coût: `cost_per_item × total` estimé avant, réel après; un plafond par traitement et par jour.

## 8. Conservation et suppression

- `proposal_decisions` et les statistiques agrégées sont **conservées** même si le traitement, la tâche ou le dataset sont
  supprimés (les colonnes dénormalisées n'ont pas de clé étrangère bloquante).
- Elles ne contiennent **ni le contenu annoté ni les réponses**, seulement des identifiants, des nombres et des dates, pour
  pouvoir les garder sans conserver de données personnelles. Durée de conservation à fixer (voir **12**).
- Les propositions `deleted` et `superseded` sont purgées au bout de 30 jours (configurable). Elles peuvent contenir le
  contenu prédit.
- Supprimer un **modèle** le passe `disabled`; ses versions et ses statistiques restent pour l'historique.

## 9. Permissions

| Action | Qui |
|---|---|
| Voir les modèles compatibles | toute personne qui peut lire la tâche |
| Lancer, arrêter, reprendre, supprimer un traitement | créateur de la tâche, maintainer du dataset, admin |
| Voir et valider les propositions | toute personne qui peut annoter la tâche |
| Rejeter une proposition | idem (cela ne touche que sa propre décision) |
| Voir les statistiques d'une tâche | créateur, maintainer, admin; les annotateurs voient seulement les leurs |
| Voir les statistiques entre tâches (`/model-stats`) | maintainer d'au moins un dataset concerné, admin |
| Gérer le catalogue de modèles | admin |

Les statistiques par annotateur (qui accepte trop vite) ne sont **jamais montrées aux autres annotateurs**.

## 10. Granularité de la confiance

Le frontend ne connaît qu'**une confiance par élément**. Les modèles en fournissent souvent plusieurs (une par boîte, par
entité, par région), et c'est plus utile: on peut ne montrer ou ne préremplir que ce qui dépasse un seuil.

- Dans `payload`, chaque objet peut avoir `confidence` (spans, boîtes, régions, pistes, paires question-réponse).
- `proposals.confidence` est l'agrégat (minimum ou moyenne, au choix du modèle) pour l'élément.
- Option de tâche à prévoir: `min_confidence` (n'afficher que les propositions au-dessus) et « seulement les éléments en
  dessous d'un seuil » pour l'apprentissage actif (voir **12**).

## 11. Correspondance avec le frontend

| Frontend | Backend |
|---|---|
| `PreRun` (`store.ts`) | `preannotation_runs` + `preannotation_run_items` |
| `Proposal` | `proposals` (`payload` = la réponse attendue) |
| `Decision`, `commitAnswer`, `rejectProposal` | `proposal_decisions`, `PUT …/annotation` avec `proposal_id`, `POST /proposals/{id}/reject` |
| `runs.ts` (`startRun`, `stopRun`, `resumeRun`, `deleteRun`, minuteur) | les routes de **5** et le worker de **4.3** |
| `models.ts` (`modelsFor`) | `GET /models?task_type=` |
| `preannotate.ts` (`makeProposal`) | un appel `POST {endpoint}/predict` (voir **7**) |
| `statsOf` | `GET …/stats` (le calcul est côté serveur; le frontend n'affiche que) |
| `Answer.origin`, `model`, `run` | `annotations.origin`, `proposal_id`, `run_id` |

Conversions à prévoir:
- Les compteurs « à valider » deviennent **par utilisateur** (voir **3.4**).
- `Proposal.runId` et `Decision` deviennent des identifiants serveur; le frontend n'invente plus de `Decision`.
- La progression passe d'un minuteur à des événements serveur (`events`) ou un sondage.
- Le calcul de `score` et d'acceptation vient du serveur; le tableau du dialogue ne fait plus que l'afficher.

## 12. Ordre de construction proposé

1. **Catalogue de modèles** (`models`, `model_versions`) et `GET /models?task_type=`; un modèle interne trivial pour tester.
2. **Lancer un traitement** sur le type de tâche le plus simple (classification de texte): table des traitements, file,
   worker, propositions, progression, arrêt, reprise, suppression, tests.
3. **Valider**: `proposal_id` sur `PUT …/annotation`, `reject`, `proposal_decisions`, provenance dans `annotations`.
4. **Statistiques et comparaison** (`stats`, `model-stats`, intervalle de Wilson), sans le mode à l'aveugle.
5. **Autres types de tâche**, un par un: pour chacun, la validation du `payload` et le calcul d'`edit_score` avec ses
   vecteurs de test.
6. **Mode à l'aveugle, éléments d'or et détection de complaisance.**
7. **Modèles externes**: politique de données, secrets, coût et plafonds.
8. **Plus tard**: apprentissage actif (proposer d'abord les éléments les plus incertains), ré-entraînement à partir des
   réponses validées, choix automatique du meilleur modèle par défaut.

Chaque étape: migration Alembic, tests, mise à jour de `docs/data-model.*`.

## 13. Questions ouvertes

1. **Plusieurs traitements en parallèle** sur la même tâche (deux modèles pour les comparer sur les mêmes éléments)? Le
   frontend n'en autorise qu'un à la fois. Comparer deux modèles sur **les mêmes éléments** donne une mesure bien plus
   juste que sur des éléments différents.
2. **Écraser les propositions d'un autre traitement** par défaut, ou les garder à côté (l'annotateur choisit)?
3. **Validation en bloc.** Accepter d'un coup toutes les propositions au-dessus d'un seuil de confiance, avec un contrôle
   par échantillon? Cela contourne l'idée d'une validation humaine par élément; à n'autoriser que sur décision explicite
   d'un maintainer, avec audit.
4. **Qui paie** le calcul, et existe-t-il des quotas par organisation?
5. **Durée de conservation** des décisions et des statistiques, et leur sort si un dataset est supprimé pour des raisons
   juridiques (droit à l'effacement).
6. **Mode à l'aveugle**: obligatoire, ou réglable par tâche? Quelle part de l'échantillon?
7. **Plusieurs annotateurs et une seule proposition.** Quand l'un l'accepte et l'autre la rejette, la décision « du
   modèle » compte-t-elle deux fois dans la statistique? Proposition: oui, une décision par annotateur, la vérité de
   référence étant tranchée par la revue.
8. **Ré-entraînement.** Les réponses validées servent-elles à améliorer le modèle, et avec quel consentement des
   propriétaires du dataset?
9. **Version des labels.** Si le créateur renomme ou décrit un label pendant un traitement, les propositions déjà faites
   gardent l'ancien sens. Faut-il les marquer périmées?
10. **Modèles internes ou externes en premier.** Les deux demandent des politiques différentes (données, coût, latence).
