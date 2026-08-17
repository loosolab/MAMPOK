# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
