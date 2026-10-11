# ADR 004: Artifact manifest, hashes and version rule

Status: accepted (2026-10-10)

Offline results (models, operating-range sets, strategies) are directories with a `manifest.json`
(`schemas/artifact-manifest.schema.json`) listing every payload file with its SHA-256. Readers verify the hashes and
reject a schema with a higher major version than they support; payload paths must be relative and free of `..`.
`npz` payloads are written deterministically. The `signature` field is reserved; cryptographic signing is a stage 4 task.
