# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Aughor has not cut a tagged release yet. The sections below describe the state of
`main`; the first tagged release will become `0.1.0`.

## [Unreleased]

### Added
- `LICENSE` (Apache-2.0), `NOTICE`, and `web/public/fonts/OFL.txt` — the project
  previously shipped no license at all.
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, this changelog, and
  GitHub issue / pull-request templates.
- Dependabot configuration for the `pip`, `npm`, and `github-actions` ecosystems.

### Changed
- The README license badge now reads Apache-2.0 (it previously claimed MIT with
  no license file present) and links to `LICENSE`.
- `web/README.md` replaced the stock `create-next-app` boilerplate.
- `evals/spider2.py` no longer defaults `SPIDER2_ROOT` to a hardcoded home
  directory.

### Removed
- Unreferenced `create-next-app` boilerplate assets from `web/public/`.

---

## Before the changelog

Aughor's development history predates this file. The engineering record lives in:

- the [git history](https://github.com/sidhasadhak/aughor/commits/main) — ~930
  commits on `main`, each tied to a pull request;
- [`ROADMAP.md`](ROADMAP.md) — what shipped, and what is next;
- [`FEATURES.md`](FEATURES.md) — a reference for each major capability and the
  files behind it.
