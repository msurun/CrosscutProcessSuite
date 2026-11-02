# Crosscut deployment

Two long-running processes share one data root:

- `crosscut-runtime`: periodic jobs (scheduler), writes runtime state.
- `crosscut-api`: FastAPI data API on 127.0.0.1:8000, read-only for datasets.

## Layout

```
/opt/crosscut/                 repo checkout + .venv (Linux)
C:\crosscut\                   repo checkout + .venv (Windows)
/var/lib/crosscut/             data root (Linux)
C:\crosscut\data\              data root (Windows, default)
  <dataset>/dataset.json       datasets
  _runtime/jobs.json           job definitions
  _runtime/state.json          last run per job
  _runtime/log.jsonl           run log, one JSON object per line
```

## Install on Linux

1. Create the account: `sudo useradd --system --home /var/lib/crosscut crosscut`.
2. Install the code: `sudo python3 -m venv /opt/crosscut/.venv`, then
   `/opt/crosscut/.venv/bin/pip install ./runtime ./api`.
3. `sudo cp deploy/crosscut-*.service /etc/systemd/system/`
4. `sudo systemctl daemon-reload && sudo systemctl enable --now crosscut-runtime crosscut-api`

## Install on Windows

1. Copy the repo to `C:\crosscut` and create `C:\crosscut\.venv` with the runtime and API packages.
2. Test with `deploy\windows\run-runtime.cmd` and `deploy\windows\run-api.cmd`.
3. Install both as services with NSSM: see `deploy\windows\install-service.md`.

## Check service health

Open the GUI Runtime view. It shows the job list, last run times and the log.
From the shell: `systemctl status crosscut-runtime` (Linux) or `nssm status CrosscutRuntime` (Windows).

## State files

- `_runtime/jobs.json`: which jobs run and how often; edited through the API.
- `_runtime/state.json`: last run and result per job; safe to read.
- `_runtime/log.jsonl`: append-only; rotate it if it grows large.

Deleting `state.json` makes every job run again on the next tick.

## Security

- Run the services under a service account with no write rights to the plant
  (OPC UA, PI, historian). The services only write under the data root.
- No secrets in these files or in the repo. Pass credentials through the
  service manager's secret store or the environment at install time, never in unit files or `.cmd` wrappers.
- The API binds to 127.0.0.1; put a reverse proxy in front of it if remote access is needed.
