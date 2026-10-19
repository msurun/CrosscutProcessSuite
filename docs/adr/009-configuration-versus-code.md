# ADR 009: Configuration is data, code is not (AGPL boundary)

Status: **proposed** (2026-10-19), awaiting the owner's decision and a lawyer's review of the clause below.
Builds on ADR 008 (AGPL-3.0-only).

## Context

Planned modules (fuzzy logic, MPC, machine learning) will let users supply rules, models and parameters. Under the
AGPL, what matters is whether such a file is *data the program reads* or *code that runs inside the program*. The
first is not covered by the licence of the engine; the second is probably a combined work. If the line is unclear,
users and their legal departments assume the worst and avoid the product.

## Decision

1. **Design rule.** User-supplied configuration, rules and models are declarative files validated against a schema in
   `schemas/` (as `fuzzy.schema.json` already does). The engine interprets them; it never executes user-supplied code
   in its own process (no plugin import, no `eval`, no embedded scripting). This is also a safety rule: a product that
   may one day write to a control system must not run arbitrary code.
2. **Extension by process boundary.** Anything that needs user code (a custom solver, a proprietary ML runtime) runs
   as a **separate program** and talks to Crosscut through the documented interfaces (REST, OPC UA, files in the
   declarative formats). If an in-process plugin API is ever needed, it needs its own ADR with an explicit plugin
   exception.
3. **Additional permission (proposed text, AGPL section 7, to be added to the licence notices by the owner after
   legal review).**

   > Additional permission under section 7 of the GNU Affero General Public License version 3: (a) Files that the
   > Program reads as input and does not execute as program code, including project and tag files, rule sets
   > conforming to the schemas in `schemas/`, parameter files of control or machine-learning models, and process data
   > recorded or produced by the Program, are not part of the Program or of any work based on it, and you may license
   > them under any terms and keep them private. (b) A separate program that exchanges data with the Program only
   > through its documented network interfaces or through files described in (a), and that neither contains nor links
   > code of the Program, is not a work based on the Program. This permission does not apply to code that is loaded or
   > executed inside the Program's process.

4. **Commercial licence.** Documented in `LICENSING.md`; offered by the owner as sole copyright holder. Contributions
   need a CLA that allows this (`CONTRIBUTING.md`).

## Consequences

- Users may keep their rules, models, configuration and results private.
- Features that would need in-process user code are out of scope until a new ADR changes this.
- Until the clause in 3 is adopted, `LICENSING.md` states the same as intent only; it is not a licence term.
- Open: lawyer review; whether AI-assisted parts of the code need a statement on authorship; confirm that no
  employer has a claim on the code (the repository already forbids employer material, see `CLAUDE.md`).
