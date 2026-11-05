# Safe Demo Import Plan

- Dry-run first; no remote writes in this phase.
- Require explicit target environment confirmation.
- Use deterministic import order from import_dependency_plan.md.
- Validate all FKs and constraints before import.
- Use demo provenance; never overwrite genuine records.
- Refuse import if schema blockers, missing refs, or user-data requirements.
- Proposed npm command for future (not run now): npm run seed:demo
EOF