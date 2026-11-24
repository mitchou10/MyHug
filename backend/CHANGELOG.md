# Changelog

## [0.10.0](https://github.com/mitchou10/MyHug/compare/backend-v0.9.0...backend-v0.10.0) (2026-11-24)


### Features

* **backend:** create, list, read, change, share and delete models ([456996d](https://github.com/mitchou10/MyHug/commit/456996d6e40c719336f4470f8d52b87641c60854))

## [0.9.0](https://github.com/mitchou10/MyHug/compare/backend-v0.8.0...backend-v0.9.0) (2026-11-24)


### Features

* **backend:** talk to MLflow through a registry port ([215ac73](https://github.com/mitchou10/MyHug/commit/215ac7372054f08ac0205cbf6e79d5bf132f9e24))

## [0.8.0](https://github.com/mitchou10/MyHug/compare/backend-v0.7.0...backend-v0.8.0) (2026-11-24)


### Features

* **backend:** add the tables of the models ([ebc79d0](https://github.com/mitchou10/MyHug/commit/ebc79d0a7d50911c3964c3e4be99f5a485f10701))

## [0.7.0](https://github.com/mitchou10/MyHug/compare/backend-v0.6.0...backend-v0.7.0) (2026-11-24)


### Features

* **infra:** add MLflow to the docker compose ([517b39f](https://github.com/mitchou10/MyHug/commit/517b39f2191b741a684ef6b6438b1b72f4937137))

## [0.6.0](https://github.com/mitchou10/MyHug/compare/backend-v0.5.0...backend-v0.6.0) (2026-11-24)


### Features

* **backend:** collect the objects of the storage that nothing points to ([c8c6390](https://github.com/mitchou10/MyHug/commit/c8c63907f98c7eead9f814cf50f52407637f55ac))
* **worker:** convert tabular files to Parquet as a derived cache ([caaaf36](https://github.com/mitchou10/MyHug/commit/caaaf3697fb21d411aa3035f5320cbe89ae7a37e))

## [0.5.0](https://github.com/mitchou10/MyHug/compare/backend-v0.4.1...backend-v0.5.0) (2026-11-24)


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

## [0.4.1](https://github.com/mitchou10/MyHug/compare/backend-v0.4.0...backend-v0.4.1) (2026-11-24)


### Bug Fixes

* **backend:** satisfy the new type checker ([d195f52](https://github.com/mitchou10/MyHug/commit/d195f5231b5b929f94df910716ed139138ba9b79))

## [0.4.0](https://github.com/mitchou10/app-starter/compare/backend-v0.3.0...backend-v0.4.0) (2026-11-04)


### Features

* **backend:** add the notifications table ([d9ab94a](https://github.com/mitchou10/app-starter/commit/d9ab94ab0e09bcbf3c9ffb1dfb57cf86a2149245))
* **backend:** let applications emit notifications and users read them ([66a3221](https://github.com/mitchou10/app-starter/commit/66a3221ba447c6fefeab8a79351a25d0e07db4fe))

## [0.3.0](https://github.com/mitchou10/app-starter/compare/backend-v0.2.0...backend-v0.3.0) (2026-11-04)


### Features

* **backend:** add the feedback tables with their default types and statuses ([63694c9](https://github.com/mitchou10/app-starter/commit/63694c957c49e57dbeb468c928b58f104870f793))
* **backend:** list, add, change and archive the feedback types and statuses ([0d606e8](https://github.com/mitchou10/app-starter/commit/0d606e83f1bfa16d6102a92c34a66f709b8bc842))
* **backend:** send feedback with screenshots, follow it and list it ([403fe76](https://github.com/mitchou10/app-starter/commit/403fe76386cd1e132d74cd60dd01b8307b0072da))


### Code Refactoring

* **backend:** share the image checks and group the service errors ([f72f28f](https://github.com/mitchou10/app-starter/commit/f72f28f64128911ec4c1049135646c779aa59237))


### Dependencies

* **backend:** measure the code that runs in greenlets ([a9adde6](https://github.com/mitchou10/app-starter/commit/a9adde65b44086a70c6b2ad3f0e806fd1b5b6cc2))

## [0.2.0](https://github.com/mitchou10/app-starter/compare/backend-v0.1.0...backend-v0.2.0) (2026-11-04)


### Features

* **backend:** add PostgreSQL, SQLAlchemy and Alembic migrations ([a867dfb](https://github.com/mitchou10/app-starter/commit/a867dfb0dfe20a3170e8091f9e0917c0e89ba22c))
* **backend:** store the profile photo in RustFS, with its reference in PostgreSQL ([80bf46c](https://github.com/mitchou10/app-starter/commit/80bf46cfc144fa9100dbbf8b40a1faabf2080e62))


### Code Refactoring

* **backend:** use pydantic models for the auth context, sessions and responses ([5c2fcd2](https://github.com/mitchou10/app-starter/commit/5c2fcd26a6f5bf92ba972e4605a3696389cc09c8))

## 0.1.0 (2026-11-04)


### Features

* add backend, frontend and CI/CD template ([783d383](https://github.com/mitchou10/app-starter/commit/783d3831f914fdea519cb2a462cf071618ad5691))
* add OIDC BFF authentication ([e3670a5](https://github.com/mitchou10/app-starter/commit/e3670a59f0cf61c3128638cdd40c077f2ab44d21))


### Dependencies

* replace httpx with httpx2 and bump backend dependencies ([a79c906](https://github.com/mitchou10/app-starter/commit/a79c9060890b384cf05415f4562f577455d09333))
