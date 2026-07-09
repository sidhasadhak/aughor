<!--
Thanks for contributing. Keep the PR focused: a bug fix and a refactor are two PRs.
-->

## What changed

<!-- One paragraph. What does this do, and why? -->

## How it was verified

<!--
Not "tests pass" — what did you actually observe?
If you ran it against a live warehouse, say which, and what you saw.
-->

- [ ] `uv run pytest -q -m "not e2e and not eval"`
- [ ] `uvx ruff@0.15.20 check .`
- [ ] `cd web && npx tsc --noEmit`
- [ ] `cd web && npm run lint:tokens && npm run lint:format && npm run lint:elements`
- [ ] `cd web && npm run gen:api` (only if a route or Pydantic model changed)

## Checklist

- [ ] New behaviour is behind a **default-off flag**, so the default install is
      byte-identical before and after this change. (Or: this is a bug fix and
      the old behaviour was wrong.)
- [ ] Every new guard has a test that proves it **fires** — not just that the
      function exists.
- [ ] No ratchet baseline was raised (ruff stays at zero; the raw-element count
      only shrinks).
- [ ] Any new persistent store honours its `AUGHOR_*_DB` env override and is
      wired into `tests/conftest.py`.
- [ ] Docs updated if this changes user-facing behaviour.

## Related issues

<!-- Closes #123 -->
