# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.3] - 2026-09-02

### Fixed

- `Mamplan.edit()`/`Mamplate.edit()` no longer raise `KeyError: Unknown field '...'` when setting a schema-valid field that has not been written before (e.g. `project.project_size`). Field validation now checks the Mamplan/Mamplate schema instead of the dict's current keys, so optional fields can be created on first write. This fixed `deploy` and `upload` crashing right after a successful deployment/upload, which left `deployment.status`, `deployment.url`, `deployment.bucket`, and `project.project_size` unset in the Mamplan file even though the deployment had already succeeded.

[3.1.3]: https://gitlab.gwdg.de/loosolab/software/mampok_v2/-/compare/v3.1.2...v3.1.3

## [3.1.2] - 2026-08-26

### Added

- `ListSet` sentinel for `MamplanBase.edit()`, to replace an entire list field in one call instead of editing it element by element.

### Fixed

- `API.edit_sharing()` no longer raises `TypeError: Field 'user' is a list` when updating `service.user`/`service.organization`. It now uses the new `ListSet` sentinel to replace the sharing lists, instead of passing a plain list to `edit()`, which `MamplanBase.edit()` rejects.

[3.1.2]: https://gitlab.gwdg.de/loosolab/software/mampok_v2/-/compare/v3.1.1...v3.1.2

## [3.1.1] - 2026-08-20

### Changed

- Pinned the `jsonschema` dependency to `>=4.18`.

### Fixed

- Directory-based Mamplan loading (used by `deploy`, `restore`, `list-expired`, and the Python API) now correctly picks up `*-shmamplan.json` files, which were previously skipped when scanning a directory.

[3.1.1]: https://gitlab.gwdg.de/loosolab/software/mampok_v2/-/compare/v3.1.0...v3.1.1

## [3.1.0] - 2026-08-17

### Breaking

- Removed the automatic special-casing of `"public"` in `service.organization` (which implicitly derived the auth user list as `["public"]`). Existing Mamplans relying on this convention now get their auth users derived from the plain `organization`/`user` merge instead. Use the explicit owner value `_public` for publicly accessible projects going forward. The Mamplan schema and docs were updated accordingly.
- Removed the `mamplan_repo` key from `config.json` (`MampokConfig`, `config_schema.json`). Since the config schema sets `additionalProperties: false`, any existing `config.json` that still contains `mamplan_repo` will now fail schema validation on load. Remove the key from your `config.json` before upgrading.

### Added

- `mampok --version` prints the installed version and exits.
- Mamplates support a new `proxy_resources` field to tune CPU/memory of the Gatekeeper auth-proxy sidecar per tool (default remains `100m`/`128Mi`). Useful for tools that proxy large uploads/downloads through the Gatekeeper.
- `mampok deploy`/`redeploy`/`restore` now print the token URL instead of the plain project URL when `auth: true`.
- `mampok edit` now accepts repeated `-e` flags for the same `section:key`, so multiple values can be appended to the same list in one call, e.g.: `-e service:organization:+:mpi-iem -e service:organization:+:mpi-fkm`.

### Changed

- Revised documentation across advanced, commands, concepts, configuration, getting_started, index, mamplans, python_api, and selection pages, including removal of the obsolete `mamplan_repo` config option from the docs.
- Trimmed and refocused the README on the actual feature set (Mamplate/Mamplan concept, installation via GitHub instead of a PyPI placeholder).

### Removed

- Dead code in `api.py`, `cli.py`, and `kubernetes/client.py`.
- Stale internal planning notes (`markdowns/*.md`) and a leftover test fixture file.

### Fixed

- `update-auth` now only affects already-deployed Mamplans (`deployment.status == true`); undeployed projects are skipped instead of incorrectly receiving an auth secret.

[3.1.0]: https://gitlab.gwdg.de/loosolab/software/mampok_v2/-/compare/v3.0.4...v3.1.0
