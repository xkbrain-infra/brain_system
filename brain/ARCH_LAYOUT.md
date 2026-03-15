# Layout (Canonical)

Canonical directories are under `/xkagent_infra`, with Brain source and specs
under `/xkagent_infra/brain`.

- `/xkagent_infra/brain/base`
- `/xkagent_infra/brain/groups`
- `/xkagent_infra/brain/infrastructure/config`
- `/xkagent_infra/brain/infrastructure/service`
- `/xkagent_infra/brain/platform`
- `/xkagent_infra/runtime`
- `/xkagent_infra/brain/secrets`
- `/xkagent_infra/brain/backup`

`/xkagent_infra/runtime` is for runtime state only: agent homes, data, logs,
memory, tmp, and publish staging. Shared service source code belongs under
`/xkagent_infra/brain/infrastructure/service`.

Historical snapshots and migrated legacy runtime artifacts belong under
`/xkagent_infra/brain/backup`.
