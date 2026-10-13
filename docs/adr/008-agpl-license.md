# ADR 008: AGPL-3.0-only

Status: accepted (2026-10-13). Supersedes ADR 005.

The owner changed the repository licence from Apache-2.0 to the GNU Affero General Public License v3.0 (GitHub, commit
920642b). The SPDX identifier used in package metadata is `AGPL-3.0-only`, because the licence text chosen carries no
"or later" option.

Consequences:
- The dependency rule of ADR 005 (avoid GPL/AGPL so that a closed-source product stays possible) no longer applies to
  the repository itself. Dependencies must still be AGPL-3.0 compatible: permissive licences (MIT, BSD, Apache-2.0) are
  fine; GPL-2.0-only code is not. Check this before adding a dependency.
- Code the owner wrote may still be offered under other terms by the owner (e.g. a commercial licence); contributions
  from others would need a contributor agreement for that, so decide before accepting any.
- Reasons for the change are not recorded here; the owner can add them.
