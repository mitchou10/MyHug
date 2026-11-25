# Changelog

## [0.25.0](https://github.com/mitchou10/MyHug/compare/v0.24.0...v0.25.0) (2026-11-25)


### Features

* **frontend:** read the evaluations of a model from the API ([5be9a0b](https://github.com/mitchou10/MyHug/commit/5be9a0b216785dda3b4b4e8601cd2299bd5fd2ae))

## [0.24.0](https://github.com/mitchou10/MyHug/compare/v0.23.0...v0.24.0) (2026-11-25)


### Features

* **backend:** store and expose the evaluations of a model ([36181e1](https://github.com/mitchou10/MyHug/commit/36181e18566d4117f220ba90ae170b778e5e825a))

## [0.23.0](https://github.com/mitchou10/MyHug/compare/v0.22.0...v0.23.0) (2026-11-25)


### Features

* **backend:** members of a dataset and its Parquet copy to read by ranges ([df2d0cf](https://github.com/mitchou10/MyHug/commit/df2d0cf835f421112c9fd3a3096762f4451d122c))
* **sdk:** datasets and models from code ([d967fa2](https://github.com/mitchou10/MyHug/commit/d967fa2e69d3c552bfa8b3dbb96c098006ccdd9c))


### Dependencies

* bump node from 22-alpine to 26-alpine in /frontend ([35bd3db](https://github.com/mitchou10/MyHug/commit/35bd3db0adaf88e0f8df4690d6da318bd81ef6a9))
* bump the npm group in /frontend with 15 updates ([38376b6](https://github.com/mitchou10/MyHug/commit/38376b690daab1e00d5ec75196ec6139d6ae229a))

## [0.22.0](https://github.com/mitchou10/MyHug/compare/v0.21.0...v0.22.0) (2026-11-25)


### Features

* **sdk:** add the core of the Python SDK ([aa0a9d6](https://github.com/mitchou10/MyHug/commit/aa0a9d699340f17e73aba10206de1ef595b7cd7d))

## [0.21.0](https://github.com/mitchou10/MyHug/compare/v0.20.0...v0.21.0) (2026-11-25)


### Features

* **backend:** access tokens for programs ([f6a24ab](https://github.com/mitchou10/MyHug/commit/f6a24abdcddd39824cba99bbd4f29a4428581e1e))

## [0.20.0](https://github.com/mitchou10/MyHug/compare/v0.19.0...v0.20.0) (2026-11-25)


### Features

* **infra:** generate the API types from the OpenAPI schema ([d0aa4bf](https://github.com/mitchou10/MyHug/commit/d0aa4bfe546a839504ed65474e4a8350a174af0b))

## [0.19.0](https://github.com/mitchou10/MyHug/compare/v0.18.0...v0.19.0) (2026-11-25)


### Features

* **frontend:** connect the models space to the API ([dce7bb9](https://github.com/mitchou10/MyHug/commit/dce7bb9d72d22369976282d569234da551a8f285))

## [0.18.0](https://github.com/mitchou10/MyHug/compare/v0.17.0...v0.18.0) (2026-11-25)


### Features

* **backend:** serve a model only where it is declared, and relay to try it ([e5d6220](https://github.com/mitchou10/MyHug/commit/e5d6220cec43f58d96a0bf982f4e81aded6c6f6f))

## [0.17.0](https://github.com/mitchou10/MyHug/compare/v0.16.0...v0.17.0) (2026-11-24)


### Features

* **worker:** pin the code of a model version to a commit ([2ed65a3](https://github.com/mitchou10/MyHug/commit/2ed65a3733e3c0ffa6ec919cb5f2d02f3ef4a354))

## [0.16.0](https://github.com/mitchou10/MyHug/compare/v0.15.0...v0.16.0) (2026-11-24)


### Features

* **worker:** fingerprint the files of a model version ([e6675d2](https://github.com/mitchou10/MyHug/commit/e6675d2ec0875ece5820dbe4229377ac1020cb9c))

## [0.15.0](https://github.com/mitchou10/MyHug/compare/v0.14.0...v0.15.0) (2026-11-24)


### Features

* **backend:** upload and download the artifacts of a model, as versions ([ce871d0](https://github.com/mitchou10/MyHug/commit/ce871d0f6405327f65c5092534b5c8c5091bbd2e))

## [0.14.0](https://github.com/mitchou10/MyHug/compare/v0.13.0...v0.14.0) (2026-11-24)


### Features

* **backend:** create, list, read, change, share and delete models ([456996d](https://github.com/mitchou10/MyHug/commit/456996d6e40c719336f4470f8d52b87641c60854))

## [0.13.0](https://github.com/mitchou10/MyHug/compare/v0.12.0...v0.13.0) (2026-11-24)


### Features

* **backend:** talk to MLflow through a registry port ([215ac73](https://github.com/mitchou10/MyHug/commit/215ac7372054f08ac0205cbf6e79d5bf132f9e24))

## [0.12.0](https://github.com/mitchou10/MyHug/compare/v0.11.0...v0.12.0) (2026-11-24)


### Features

* **backend:** add the tables of the models ([ebc79d0](https://github.com/mitchou10/MyHug/commit/ebc79d0a7d50911c3964c3e4be99f5a485f10701))

## [0.11.0](https://github.com/mitchou10/MyHug/compare/v0.10.0...v0.11.0) (2026-11-24)


### Features

* **infra:** add MLflow to the docker compose ([517b39f](https://github.com/mitchou10/MyHug/commit/517b39f2191b741a684ef6b6438b1b72f4937137))

## [0.10.0](https://github.com/mitchou10/MyHug/compare/v0.9.0...v0.10.0) (2026-11-24)


### Features

* **backend:** collect the objects of the storage that nothing points to ([c8c6390](https://github.com/mitchou10/MyHug/commit/c8c63907f98c7eead9f814cf50f52407637f55ac))
* **worker:** convert tabular files to Parquet as a derived cache ([caaaf36](https://github.com/mitchou10/MyHug/commit/caaaf3697fb21d411aa3035f5320cbe89ae7a37e))

## [0.9.0](https://github.com/mitchou10/MyHug/compare/v0.8.1...v0.9.0) (2026-11-24)


### Features

* **backend:** add the tables of the datasets ([035d29a](https://github.com/mitchou10/MyHug/commit/035d29a29782340e97833cbae2ed31b4155eee20))
* **backend:** create, list, read, change and delete datasets, with their files ([1b0fa4d](https://github.com/mitchou10/MyHug/commit/1b0fa4daf04fe818117e18d91c0c9af78f046651))
* **backend:** do not send again a file the dataset already holds ([6b6aa02](https://github.com/mitchou10/MyHug/commit/6b6aa022d33eec3a1d5e96f5aceeb6582e5a736b))
* **backend:** leave the reading of the dataset files to a worker ([b308ccc](https://github.com/mitchou10/MyHug/commit/b308ccc1d98cbd6cecab27d2e834fe31b4c13baa))
* **backend:** read the dataset files in a Celery worker, with Redis ([e01de8e](https://github.com/mitchou10/MyHug/commit/e01de8e569b3a5ba934470f8d94d34bd89238aeb))
* **backend:** upload the files of a dataset in parts, straight to the storage ([765e65b](https://github.com/mitchou10/MyHug/commit/765e65bf8af302e7a1c31003b32b797844af4348))
* **worker:** move the reading of the dataset files to a service of its own ([1fdbbd7](https://github.com/mitchou10/MyHug/commit/1fdbbd747f80e563897e059e1c4c304f8eda9a44))


### Bug Fixes

* **backend:** sign the storage addresses with signature version 4 ([93a27d3](https://github.com/mitchou10/MyHug/commit/93a27d364d1e6c60e1e71663bad3adc9fcedda75))

## [0.8.1](https://github.com/mitchou10/MyHug/compare/v0.8.0...v0.8.1) (2026-11-24)


### Bug Fixes

* **ci:** scan the images by their lowercase name ([bdda22e](https://github.com/mitchou10/MyHug/commit/bdda22eb9e5752a4501ef02da4a06828d6b53211))

## [0.8.0](https://github.com/mitchou10/MyHug/compare/v0.7.0...v0.8.0) (2026-11-24)


### Features

* **collections:** gather datasets and models in collections ([e5a96c1](https://github.com/mitchou10/MyHug/commit/e5a96c1a6bd1398cc122e9093a5a796b24934855))
* **datasets:** link the pre-annotation to the page of its model ([a41e1b6](https://github.com/mitchou10/MyHug/commit/a41e1b6748114de8c259c0cd3c158fea4098ae46))
* **models:** add a space for models, like the one for datasets ([ca9a63e](https://github.com/mitchou10/MyHug/commit/ca9a63ec540500b217594095fc8ba4e190a9c866))
* **models:** evaluate a model with the important metrics of its tasks ([367e94a](https://github.com/mitchou10/MyHug/commit/367e94ae5ab986298c99df541872a06c26d75662))

## [0.7.0](https://github.com/mitchou10/MyHug/compare/v0.6.0...v0.7.0) (2026-11-24)


### Features

* **datasets:** pre-annotate tasks with a model, validated by a human ([5160e7a](https://github.com/mitchou10/MyHug/commit/5160e7a1264d00918f62414009788440eff8e5bf))

## [0.6.0](https://github.com/mitchou10/MyHug/compare/v0.5.0...v0.6.0) (2026-11-24)


### Features

* **datasets:** add annotation tasks for text datasets ([96cc689](https://github.com/mitchou10/MyHug/commit/96cc689e8e1585a78de66e2e3aa29dc84422ae1a))
* **datasets:** add mock datasets and a viewer for each modality ([f4f704c](https://github.com/mitchou10/MyHug/commit/f4f704ceee47df148009318c49f7a7a173b6c6b2))
* **datasets:** add several question-answer pairs per text with highlighted sources ([700319e](https://github.com/mitchou10/MyHug/commit/700319e892efdd0e2ccba6a141f0692195049217))
* **datasets:** add the dataset list and detail pages ([1b9855a](https://github.com/mitchou10/MyHug/commit/1b9855ad45a991af9926ac1d5b27a0e598b4d095))
* **datasets:** allow several labels on classification tasks ([7eb0915](https://github.com/mitchou10/MyHug/commit/7eb0915c347054a864756671f681d9acfe559c88))
* **datasets:** annotate audio ([d72daf2](https://github.com/mitchou10/MyHug/commit/d72daf22dfaca959716a531a43875102b5b16c2e))
* **datasets:** annotate images ([141bd87](https://github.com/mitchou10/MyHug/commit/141bd87cb568eae1d3d7f2c4c85d7e1847063626))
* **datasets:** annotate tabular datasets and add regression tasks ([ec123c4](https://github.com/mitchou10/MyHug/commit/ec123c45a2a4ecea3e76f3bb36bbbc3eff5b3b15))
* **datasets:** annotate time series ([de5ce1b](https://github.com/mitchou10/MyHug/commit/de5ce1bec93d60852c1d6f9f3b2fe1f94f83a334))
* **datasets:** annotate videos ([bbb0a0e](https://github.com/mitchou10/MyHug/commit/bbb0a0eb8337406ece51db464b30d731577f72b8))


### Bug Fixes

* **backend:** satisfy the new type checker ([d195f52](https://github.com/mitchou10/MyHug/commit/d195f5231b5b929f94df910716ed139138ba9b79))
* **datasets:** keep the buttons of the edit modals in view ([bfc68a8](https://github.com/mitchou10/MyHug/commit/bfc68a8be31d104953057ac7d1be5b27532d0ceb))

## [0.5.0](https://github.com/mitchou10/app-starter/compare/v0.4.0...v0.5.0) (2026-11-04)


### Features

* **backend:** add the notifications table ([d9ab94a](https://github.com/mitchou10/app-starter/commit/d9ab94ab0e09bcbf3c9ffb1dfb57cf86a2149245))
* **backend:** let applications emit notifications and users read them ([66a3221](https://github.com/mitchou10/app-starter/commit/66a3221ba447c6fefeab8a79351a25d0e07db4fe))
* **frontend:** add the notifications page and the badge on the avatar ([d4177ad](https://github.com/mitchou10/app-starter/commit/d4177ad0ef7450c28b93ca9413c7e2ef19946120))


### Code Refactoring

* **frontend:** share the API client and the error messages ([0df72b1](https://github.com/mitchou10/app-starter/commit/0df72b1239bf106130c6d9d46967bb3179d6d83b))

## [0.4.0](https://github.com/mitchou10/app-starter/compare/v0.3.0...v0.4.0) (2026-11-04)


### Features

* add a plain user to the Keycloak realm ([dc31a19](https://github.com/mitchou10/app-starter/commit/dc31a19605a02a1cfdd5052f6205e8e2f97f7766))
* **frontend:** add a favicon ([e7a2baa](https://github.com/mitchou10/app-starter/commit/e7a2baa95180bd0696bd337f6088925988e42ed2))
* **frontend:** add the feedback screens, on an in-memory mock ([de0a69d](https://github.com/mitchou10/app-starter/commit/de0a69d101b3df69f41201e0bf13c26d3b6b529d))
* **frontend:** add the layer that talks to the feedback API ([9df20ca](https://github.com/mitchou10/app-starter/commit/9df20ca54fffe08cc6692f225288a666983bef5b))
* **frontend:** open Give feedback with Ctrl+Shift+F and attach the page the user is on ([9a5aa25](https://github.com/mitchou10/app-starter/commit/9a5aa256da576e3b374d967ec0038de03014d93e))
* **frontend:** read and write the feedback through the API ([8415cc5](https://github.com/mitchou10/app-starter/commit/8415cc5da1c95249a14a4ca15de90f155301388c))
* **frontend:** scroll the follow-up on its own and paginate the feedback list ([6bef123](https://github.com/mitchou10/app-starter/commit/6bef1230cb20cd80febcb5d2759d48df1391ec68))


### Code Refactoring

* **frontend:** one feedback page per side, with the list and the detail together ([5ef0d19](https://github.com/mitchou10/app-starter/commit/5ef0d19b7c7e91aa86f79aab8e423746fa825376))


### Dependencies

* **frontend:** add TanStack Query ([a6d188f](https://github.com/mitchou10/app-starter/commit/a6d188f80f4f3c21e5cdedde1f6df5de270cdfc8))
* **frontend:** add the shadcn dialog, textarea, badge, table, label and tabs components ([287fb7a](https://github.com/mitchou10/app-starter/commit/287fb7a2712f9e9bb27ac0c08103e5c23e17a830))

## [0.3.0](https://github.com/mitchou10/app-starter/compare/v0.2.0...v0.3.0) (2026-11-04)


### Features

* **backend:** add the feedback tables with their default types and statuses ([63694c9](https://github.com/mitchou10/app-starter/commit/63694c957c49e57dbeb468c928b58f104870f793))
* **backend:** list, add, change and archive the feedback types and statuses ([0d606e8](https://github.com/mitchou10/app-starter/commit/0d606e83f1bfa16d6102a92c34a66f709b8bc842))
* **backend:** send feedback with screenshots, follow it and list it ([403fe76](https://github.com/mitchou10/app-starter/commit/403fe76386cd1e132d74cd60dd01b8307b0072da))


### Code Refactoring

* **backend:** share the image checks and group the service errors ([f72f28f](https://github.com/mitchou10/app-starter/commit/f72f28f64128911ec4c1049135646c779aa59237))


### Dependencies

* **backend:** measure the code that runs in greenlets ([a9adde6](https://github.com/mitchou10/app-starter/commit/a9adde65b44086a70c6b2ad3f0e806fd1b5b6cc2))

## [0.2.0](https://github.com/mitchou10/app-starter/compare/v0.1.0...v0.2.0) (2026-11-04)


### Features

* **backend:** add PostgreSQL, SQLAlchemy and Alembic migrations ([a867dfb](https://github.com/mitchou10/app-starter/commit/a867dfb0dfe20a3170e8091f9e0917c0e89ba22c))
* **backend:** store the profile photo in RustFS, with its reference in PostgreSQL ([80bf46c](https://github.com/mitchou10/app-starter/commit/80bf46cfc144fa9100dbbf8b40a1faabf2080e62))
* **frontend:** add the profile photo to the settings page and the sidebar ([54dcf0a](https://github.com/mitchou10/app-starter/commit/54dcf0a73f4eec96928e84c6e142b75680b5c602))


### Code Refactoring

* **backend:** use pydantic models for the auth context, sessions and responses ([5c2fcd2](https://github.com/mitchou10/app-starter/commit/5c2fcd26a6f5bf92ba972e4605a3696389cc09c8))

## 0.1.0 (2026-11-04)


### Features

* add backend, frontend and CI/CD template ([783d383](https://github.com/mitchou10/app-starter/commit/783d3831f914fdea519cb2a462cf071618ad5691))
* add OIDC BFF authentication ([e3670a5](https://github.com/mitchou10/app-starter/commit/e3670a59f0cf61c3128638cdd40c077f2ab44d21))
* **frontend:** add a landing page and routing with a protected route ([5a1d868](https://github.com/mitchou10/app-starter/commit/5a1d86898e08721c469cfe7b83b039f975055e50))
* **frontend:** add an app layout with a sidebar and a profile menu ([815716e](https://github.com/mitchou10/app-starter/commit/815716ed119693cb6af6f5e89d831f325a210abb))
* **frontend:** add reusable layout components and a language dropdown ([29218e5](https://github.com/mitchou10/app-starter/commit/29218e50c110838f5b010e2bc49f594aba00ba58))
* rebuild the frontend with React, Tailwind, shadcn/ui and i18next ([401b41c](https://github.com/mitchou10/app-starter/commit/401b41c928190511ae7bb7cd8f2738d9e9f153e8))
* style the Keycloak login page like the frontend ([5e0b488](https://github.com/mitchou10/app-starter/commit/5e0b48809aa4f80dd17dbaa05a7aa1cfb363ed79))


### Bug Fixes

* **frontend:** track src/lib, ignored by the root .gitignore ([cf96985](https://github.com/mitchou10/app-starter/commit/cf969858e403f92e42ce23f1663ccbe8637bbe32))


### Dependencies

* add react-router to the frontend ([ccca7ef](https://github.com/mitchou10/app-starter/commit/ccca7ef1aeb0489d08f59339b7e83df9f9550de9))
* **frontend:** add the shadcn sidebar, dropdown menu and avatar components ([ecb0897](https://github.com/mitchou10/app-starter/commit/ecb0897c78e29422d6455014b38c75d1c6e52ee7))
* replace httpx with httpx2 and bump backend dependencies ([a79c906](https://github.com/mitchou10/app-starter/commit/a79c9060890b384cf05415f4562f577455d09333))
