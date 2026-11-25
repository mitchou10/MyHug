# Changelog

## [0.11.0](https://github.com/mitchou10/MyHug/compare/frontend-v0.10.0...frontend-v0.11.0) (2026-11-25)


### Features

* **backend:** members of a dataset and its Parquet copy to read by ranges ([df2d0cf](https://github.com/mitchou10/MyHug/commit/df2d0cf835f421112c9fd3a3096762f4451d122c))


### Dependencies

* bump node from 22-alpine to 26-alpine in /frontend ([35bd3db](https://github.com/mitchou10/MyHug/commit/35bd3db0adaf88e0f8df4690d6da318bd81ef6a9))
* bump the npm group in /frontend with 15 updates ([38376b6](https://github.com/mitchou10/MyHug/commit/38376b690daab1e00d5ec75196ec6139d6ae229a))

## [0.10.0](https://github.com/mitchou10/MyHug/compare/frontend-v0.9.0...frontend-v0.10.0) (2026-11-25)


### Features

* **backend:** access tokens for programs ([f6a24ab](https://github.com/mitchou10/MyHug/commit/f6a24abdcddd39824cba99bbd4f29a4428581e1e))

## [0.9.0](https://github.com/mitchou10/MyHug/compare/frontend-v0.8.0...frontend-v0.9.0) (2026-11-25)


### Features

* **infra:** generate the API types from the OpenAPI schema ([d0aa4bf](https://github.com/mitchou10/MyHug/commit/d0aa4bfe546a839504ed65474e4a8350a174af0b))

## [0.8.0](https://github.com/mitchou10/MyHug/compare/frontend-v0.7.0...frontend-v0.8.0) (2026-11-25)


### Features

* **frontend:** connect the models space to the API ([dce7bb9](https://github.com/mitchou10/MyHug/commit/dce7bb9d72d22369976282d569234da551a8f285))

## [0.7.0](https://github.com/mitchou10/MyHug/compare/frontend-v0.6.0...frontend-v0.7.0) (2026-11-24)


### Features

* **collections:** gather datasets and models in collections ([e5a96c1](https://github.com/mitchou10/MyHug/commit/e5a96c1a6bd1398cc122e9093a5a796b24934855))
* **datasets:** link the pre-annotation to the page of its model ([a41e1b6](https://github.com/mitchou10/MyHug/commit/a41e1b6748114de8c259c0cd3c158fea4098ae46))
* **models:** add a space for models, like the one for datasets ([ca9a63e](https://github.com/mitchou10/MyHug/commit/ca9a63ec540500b217594095fc8ba4e190a9c866))
* **models:** evaluate a model with the important metrics of its tasks ([367e94a](https://github.com/mitchou10/MyHug/commit/367e94ae5ab986298c99df541872a06c26d75662))

## [0.6.0](https://github.com/mitchou10/MyHug/compare/frontend-v0.5.0...frontend-v0.6.0) (2026-11-24)


### Features

* **datasets:** pre-annotate tasks with a model, validated by a human ([5160e7a](https://github.com/mitchou10/MyHug/commit/5160e7a1264d00918f62414009788440eff8e5bf))

## [0.5.0](https://github.com/mitchou10/MyHug/compare/frontend-v0.4.0...frontend-v0.5.0) (2026-11-24)


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

* **datasets:** keep the buttons of the edit modals in view ([bfc68a8](https://github.com/mitchou10/MyHug/commit/bfc68a8be31d104953057ac7d1be5b27532d0ceb))

## [0.4.0](https://github.com/mitchou10/app-starter/compare/frontend-v0.3.0...frontend-v0.4.0) (2026-11-04)


### Features

* **frontend:** add the notifications page and the badge on the avatar ([d4177ad](https://github.com/mitchou10/app-starter/commit/d4177ad0ef7450c28b93ca9413c7e2ef19946120))


### Code Refactoring

* **frontend:** share the API client and the error messages ([0df72b1](https://github.com/mitchou10/app-starter/commit/0df72b1239bf106130c6d9d46967bb3179d6d83b))

## [0.3.0](https://github.com/mitchou10/app-starter/compare/frontend-v0.2.0...frontend-v0.3.0) (2026-11-04)


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

## [0.2.0](https://github.com/mitchou10/app-starter/compare/frontend-v0.1.0...frontend-v0.2.0) (2026-11-04)


### Features

* **frontend:** add the profile photo to the settings page and the sidebar ([54dcf0a](https://github.com/mitchou10/app-starter/commit/54dcf0a73f4eec96928e84c6e142b75680b5c602))

## 0.1.0 (2026-11-04)


### Features

* add backend, frontend and CI/CD template ([783d383](https://github.com/mitchou10/app-starter/commit/783d3831f914fdea519cb2a462cf071618ad5691))
* add OIDC BFF authentication ([e3670a5](https://github.com/mitchou10/app-starter/commit/e3670a59f0cf61c3128638cdd40c077f2ab44d21))
* **frontend:** add a landing page and routing with a protected route ([5a1d868](https://github.com/mitchou10/app-starter/commit/5a1d86898e08721c469cfe7b83b039f975055e50))
* **frontend:** add an app layout with a sidebar and a profile menu ([815716e](https://github.com/mitchou10/app-starter/commit/815716ed119693cb6af6f5e89d831f325a210abb))
* **frontend:** add reusable layout components and a language dropdown ([29218e5](https://github.com/mitchou10/app-starter/commit/29218e50c110838f5b010e2bc49f594aba00ba58))
* rebuild the frontend with React, Tailwind, shadcn/ui and i18next ([401b41c](https://github.com/mitchou10/app-starter/commit/401b41c928190511ae7bb7cd8f2738d9e9f153e8))


### Bug Fixes

* **frontend:** track src/lib, ignored by the root .gitignore ([cf96985](https://github.com/mitchou10/app-starter/commit/cf969858e403f92e42ce23f1663ccbe8637bbe32))


### Dependencies

* add react-router to the frontend ([ccca7ef](https://github.com/mitchou10/app-starter/commit/ccca7ef1aeb0489d08f59339b7e83df9f9550de9))
* **frontend:** add the shadcn sidebar, dropdown menu and avatar components ([ecb0897](https://github.com/mitchou10/app-starter/commit/ecb0897c78e29422d6455014b38c75d1c6e52ee7))
