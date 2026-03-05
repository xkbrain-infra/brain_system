# brain_gateway Rollback

`brain_gateway` now includes a guarded release switch tool:

- Script: `bin/brain_gatewayctl`
- Purpose: snapshot current runtime pointers + config, promote release, auto-rollback on health-check failure.

## Commands

```bash
bin/brain_gatewayctl snapshot --label before_change
bin/brain_gatewayctl list
bin/brain_gatewayctl status --health-url http://127.0.0.1:8200/health
bin/brain_gatewayctl promote --release v0.1.1 --health-url http://127.0.0.1:8200/health --timeout 20
bin/brain_gatewayctl rollback --snapshot 20260305T135236Z_before_change
```

## What Gets Snapshotted

- `bin/current` target release path
- `config/brain_gateway.json`
- metadata (`backups/<snapshot_id>/meta.json`)

## Promote Safety Flow

1. Auto-create snapshot (`auto_before_promote_<release>`)
2. Switch `bin/current` symlink to target release
3. Restart tmux session (default: `brain_gateway`)
4. Health-check `/health`
5. If failed: restore snapshot and restart again

## Notes

- Session name can be overridden via env:
  - `BRAIN_GATEWAY_TMUX_SESSION=<name> bin/brain_gatewayctl ...`
- `promote` requires release binary:
  - `releases/<version>/bin/brain_gateway`
