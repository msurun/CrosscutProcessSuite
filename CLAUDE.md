# Crosscut Process Suite: instructions for AI sessions

1. **Start by reading `docs/PRODUCT.md`, then `docs/IMPLEMENTATION_LOG.md`** (state, ordered task board, open items). Update it before ending a work block.
2. Language: code, comments, identifiers, commit messages, README and docs are in English.
3. Data and provenance: all data is synthetic. Never use code, data, parameters or results from any employer. Add a row to
   `docs/PROVENANCE.md` (public source) before implementing a method.
4. Contracts first: `schemas/*.schema.json` are the source of truth; change a schema together with its tests.
5. Quality gates before every commit: `python -m ruff check .` and `python -m pytest` (and mypy for new typed packages).
6. Do not publish packages to PyPI/npm. Do not commit generated data (`data/`, `*.parquet`, `.agent-out/`).
7. Private planning documents (Polish) are intentionally not in this repo; never copy their personal or strategic content here.
8. Prefer small, verified steps: write the tests first, then the implementation.
9. Write teaching comments together with the code, not in a later pass: numerical and domain code states the model, the
   formula, the units and the data structure where it is used. When delegating, ask for them in the prompt and attach the
   whole file (or the contract files) as context; a model that sees one function writes comments that are wrong or vacuous.
   `dev/comment_review.py` re-checks comments with whole-file context.
10. Every source file starts with a short header (2-4 lines) saying what the file does and why it exists: a module
    docstring in Python, a `//` comment block in TypeScript and C++. The style gate enforces it for Python only.
11. **Product scope.** `docs/PRODUCT.md` is the product definition. Every task names its module and phase there. Work on plant data yields a generic engine feature plus an example configuration, or nothing. A new top-level element (package, experiment line, tool) needs the owner's approval. Writes to a control system go only through the Write Gateway (ADR 012).

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
