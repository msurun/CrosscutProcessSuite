# Crosscut in Docker

This folder holds the Linux on-prem container deployment for issue #169:

- `Dockerfile` builds the console with Node and installs the Python packages into
  one pinned, non-root runtime image.
- `docker-compose.yml` runs `api`, `runtime` and `gateway` as separate containers
  with two named volumes (`crosscut-data`, `crosscut-gateway`) and healthchecks.
- `.env.example` documents every setting. Copy it outside the repository; it is
  never a place for committed secrets.

The install, upgrade, backup, log and secret procedures are in
`docs/ADMIN_GUIDE.md`, section "Docker Compose deployment". The short version:

```sh
sudo install -d -m 0750 /etc/crosscut
sudo cp deploy/docker/.env.example /etc/crosscut/crosscut.env
sudo chmod 0600 /etc/crosscut/crosscut.env
docker compose -f deploy/docker/docker-compose.yml \
  --env-file /etc/crosscut/crosscut.env up -d --build
```

The gateway is the only writer to the plant (ADR 012). It mounts the data root
read-only and writes only inside its own `crosscut-gateway` volume, which also
holds the policy, audit log and 0640 HMAC key.
