# Licensing of Crosscut

Crosscut is free software under the **GNU Affero General Public License v3.0** (`AGPL-3.0-only`, see
[LICENSE](LICENSE)). A **commercial licence** is also available for users who cannot or do not want to work under the
AGPL.

## Open source use (AGPL-3.0)

You may use, study, modify and share Crosscut under the AGPL. In short:

- Running Crosscut unchanged, for any purpose, carries no obligation to publish anything.
- If you pass Crosscut on, or offer a **modified** version to users over a network, you must offer those users the
  source of your version under the AGPL.
- A program that includes or links Crosscut code becomes part of the same work and falls under the same rule.

## Your configuration, rules and models

The licensor's intent: files that Crosscut **reads as data** are yours, and you do not have to publish them. This
covers project and tag files, fuzzy rule sets (JSON, `schemas/fuzzy.schema.json`), model parameters for MPC and
machine learning, and your process data and results. Code that runs *inside* the Crosscut process (plugins, scripts
that import Crosscut) is a different matter and is treated as part of the work. See
[ADR 009](docs/adr/009-configuration-versus-code.md), which also proposes a formal additional permission that makes
this binding. Until that permission is adopted, this paragraph is a statement of intent, not a licence term.

## Commercial licence

A commercial licence lets you use, modify and embed Crosscut **without the AGPL obligations** (for example, to keep
your changes private or to ship Crosscut inside a closed product). Terms are agreed per customer; there is no
standard price list.

Contact: **[to be filled in by the owner before publication]**

The commercial licence is offered by the copyright holder, who wrote all code in this repository (see
`git shortlog`). Contributions from others are accepted only under an agreement that allows this; see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Third-party data and dependencies

Third-party datasets (SACAC, ISDB) are not part of this repository and are not covered by either licence; see
[docs/PROVENANCE.md](docs/PROVENANCE.md). Dependencies keep their own licences and must be AGPL-compatible
(permissive licences are fine).
