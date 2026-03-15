# Infrastructure Backups

This directory holds retired infrastructure snapshots and migration backups.

- Canonical live runtime root: `/xkagent_infra/runtime/`
- Canonical live service/config roots: `/xkagent_infra/brain/infrastructure/service/` and `/xkagent_infra/brain/infrastructure/config/`
- Contents here are archival only

Do not write live logs, live databases, offsets, or other runtime-generated
state into this directory.
