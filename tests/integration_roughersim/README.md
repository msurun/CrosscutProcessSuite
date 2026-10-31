# RougherSim pin and golden hashes

Crosscut pins one RougherSim release in `pin.json` (`tag`, `commit_sha`) and guards a
sha256 per `<scenario_id>/<seed>` in `goldens`. The recipe is in the docstring of
`golden.py::golden_hash`.

Run (about 100 s per scenario, marked `slow`; deselect with `-m "not slow"`):

    python -m pytest tests/integration_roughersim

The RougherSim checkout is `ROUGHERSIM_DIR` or the sibling `../RougherSim`; its venv
(`.venv`, or the interpreter in `ROUGHERSIM_PYTHON`) records the scenario via `roughersim record`. The test skips with a message when the
checkout is missing, has local modifications under `src`, `scenarios` or `profiles`, or is not the pinned commit. It fails only when the
checkout IS the pinned commit and a golden differs.

## Golden mismatch

On the pinned commit a mismatch means the simulator output changed under the same tag
(non-determinism or a platform difference), or the recipe changed. RougherSim's rule
(`docs/CONTRACT.md` section 5): a model change that moves a golden hash is a minor version bump
with a `CHANGELOG.md` entry, so a real change always comes with a new tag.

## Bump the pin

1. Edit `tag` and `commit_sha` in `pin.json` by hand (never automatic).
2. Check out that tag in the RougherSim checkout.
3. Run `python -m pytest tests/integration_roughersim --update-goldens`. It rewrites only the
   `goldens` map from the current checkout and never touches `tag` or `commit_sha`.
4. Review the diff of `pin.json`, run the other gates and commit it together with the reason
   (RougherSim CHANGELOG entry).

`--update-goldens` is registered by `conftest.py` in this folder, so pass this folder on the
command line.
