# API endpoints without a GUI - audit (#177)

Audit of CrosscutProcessSuite API endpoints that had no GUI caller in the issue list. Callers were checked against `frontend/src` (api.ts, authApi.ts, components, pages), against internal Python callers, and against the docs. No endpoint qualifies for removal on the evidence found.

| endpoint | handler file:line | callers found now | recommendation | one-line reason |
|---|---|---|---|---|
| POST /users/{username}/password-reset | api/src/crosscut_api/auth_pending_routes.py:34 (`password_reset`), route at :102 | No frontend caller. UsersPage.tsx:202-203 resets via PATCH instead | GUI action | Under the default two-admin rule the GUI path is broken: PATCH with a password returns 409 (auth_user_routes.py:280). Wire the reset modal to this POST and show the pending-approval state (202). |
| GET /auth/settings | api/src/crosscut_api/auth_routes.py:173 (`settings`), route at :361 | No frontend caller. Tested in api/tests/test_auth_settings.py. Documented in docs/ADMIN_GUIDE.md:63, 77 | Keep as internal (optional GUI read-only view) | Read-only admin settings view, documented for operators; no write path needed in the GUI. |
| POST /supervisor/propose | api/src/crosscut_api/supervisor_routes.py:164 (`post_propose`), route at :357 | No frontend caller. Tested in test_supervisor_gateway_propose.py and test_supervisor_propose_rules.py | GUI action | Creates proposals that the owner must confirm; belongs in the supervisor view as a propose action. |
| GET /gateway/mv-availability | api/src/crosscut_api/gateway_routes.py:312 (`get_mv_availability`), route at :423 | No frontend caller. Used by gateway_client.py:317 (`mv_availability`) | Keep as internal (controller-facing) | Controller-facing per PRODUCT.md 3.2; the GUI could show a read-only badge later, but it is not required now. |
| GET /site, PUT /site | api/src/crosscut_api/site_routes.py:31 (`get_site`), :35 (`put_site`) | frontend/src/components/EquipmentEditor.tsx:14, frontend/src/components/EquipmentAnomaliesPage.tsx:29 | Keep (already GUI) | Not orphaned; the earlier issue list missed the frontend callers. |
| GET /site/import-settings | api/src/crosscut_api/site_routes.py:43 (`get_import_settings`), route at :67 | No frontend caller. Tested in test_site_routes.py and test_site_routes_catalogue.py | GUI action (Import view), or internal if the owner declines | Import settings are needed to explain what an import will do; show them read-only in the Import view. |
| POST /fuzzy/matrix | api/src/crosscut_api/fuzzy_routes.py:187 (`post_matrix`), route at :252 | No frontend caller. Tested in test_fuzzy_backtest_routes.py. Calls `crosscut_fuzzy.matrix.rule_matrix` | GUI action (Fuzzy Studio) | PRODUCT.md:309 specifies the rule matrix grid in the Fuzzy Studio; the endpoint backs it and should be wired there. Remove only if the owner declines that screen. |

## Notes

- Items marked "GUI action" need a frontend slice (strings, tests, e2e axe check) per the GUI-for-everything rule.
- Items marked "Keep as internal" stay API-only; document them rather than remove them.
- Docs references checked: docs/ADMIN_GUIDE.md:63, 77; docs/adr/013-roles-and-authority.md:233; docs/IMPLEMENTATION_LOG.md:398, 895, 1045, 1059-1060, 1132; docs/PHASE1_PLAN.md:54; docs/PRODUCT.md:392, 429.
