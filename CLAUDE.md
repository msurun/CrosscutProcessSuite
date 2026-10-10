# Crosscut Process Suite: instructions for AI sessions

1. **Start by reading `docs/IMPLEMENTATION_LOG.md`** (state, ordered task board, open items). Update it before ending a work block.
2. Language: code, comments, identifiers, commit messages, README and docs are in English.
3. Data and provenance: all data is synthetic. Never use code, data, parameters or results from any employer. Add a row to
   `docs/PROVENANCE.md` (public source) before implementing a method.
4. Contracts first: `schemas/*.schema.json` are the source of truth; change a schema together with its tests.
5. Quality gates before every commit: `python -m ruff check .` and `python -m pytest` (and mypy for new typed packages).
6. Do not publish packages to PyPI/npm. Do not commit generated data (`data/`, `*.parquet`, `.agent-out/`).
7. Private planning documents (Polish) are intentionally not in this repo; never copy their personal or strategic content here.
8. Prefer small, verified steps: write the tests first, then the implementation.
