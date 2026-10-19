# Contributing

Thank you for considering a contribution. Two rules matter before any code is merged.

1. **Licence agreement (CLA).** Crosscut is offered under the AGPL-3.0 and, in parallel, under a commercial licence
   ([LICENSING.md](LICENSING.md)). To keep that possible, every contribution must come with a signed contributor
   agreement that lets the project owner license your contribution under both. Pull requests without it are not
   merged. The GitHub check `license/cla` enforces this.
2. **Configuration is data, not code.** Rules, models and project settings must stay declarative files validated by a
   schema in `schemas/`. Do not add features that execute user-supplied code inside the Crosscut process (plugin
   loading, `eval`, embedded scripts); see [ADR 009](docs/adr/009-configuration-versus-code.md).

Quality gates before a pull request: `python -m ruff check .`, `python -m mypy sim loops/src api/src connectors/src`,
`python -m pytest`. Method sources go into [docs/PROVENANCE.md](docs/PROVENANCE.md) before the code. Everything in the
repository is written in English; all data is synthetic.
