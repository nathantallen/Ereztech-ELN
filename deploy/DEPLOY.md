# Deploying EreZtech Operations to a server

## What you need on the server
- Docker Engine 20.10+ with the compose plugin (`docker compose version`)
- The three files from this folder: `erezops-app-1.0.0.tar.gz`,
  `docker-compose.prod.yml`, `.env.example`
- x86_64 (amd64) server — the image is built for `linux/amd64`.
  (Ask for an arm64 build if the server is ARM.)

## 1. Copy files to the server

```sh
scp erezops-app-1.0.0.tar.gz docker-compose.prod.yml .env.example user@server:/opt/erezops/
```

## 2. Load the image

```sh
cd /opt/erezops
gunzip -c erezops-app-1.0.0.tar.gz | docker load     # prints: Loaded image: erezops-app:1.0.0
```

## 3. Configure

```sh
cp .env.example .env
openssl rand -hex 16    # → POSTGRES_PASSWORD
openssl rand -hex 32    # → SECRET_KEY
nano .env               # paste both, set APP_PORT if 8090 is taken
```

Edit `docker-compose.prod.yml` and mount the server's document shares under
`/shares/...` (read-only) so the Browse… dialog can see them — examples are
commented in the file. If the server mounts your file share at `/mnt/rd`,
add `- /mnt/rd:/shares/rd:ro`.

## 4. Start

```sh
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f app   # wait for "Database ready."
```

Open `http://server:8090`.

## 5. First login — do immediately
1. Sign in as `admin` / `ereztech`.
2. **Users** → change every seeded password (admin, pmanager, qcmanager,
   rdirector, researcher1) or disable the accounts you don't need.
3. **Doc Roots** → register each mounted share (container path `/shares/rd`,
   link prefix `\\fileserver\rd` or your SharePoint URL) and delete the sample
   "Shares" root if unused.

## Operations

| Task | Command |
|---|---|
| Stop / start | `docker compose -f docker-compose.prod.yml down` / `up -d` |
| Logs | `docker compose -f docker-compose.prod.yml logs -f app` |
| DB backup | `docker compose -f docker-compose.prod.yml exec db pg_dump -U erezops erezops > erezops-$(date +%F).sql` |
| DB restore | `cat backup.sql \| docker compose -f docker-compose.prod.yml exec -T db psql -U erezops erezops` |
| Upgrade | load new image tar, bump the `image:` tag in the compose file, `up -d` (schema updates run automatically at start; data is kept in the `pgdata` volume) |

## Recommended: HTTPS
The container serves plain HTTP on the app port. For LAN-only use that may be
fine; otherwise put nginx/Caddy/Traefik in front. Caddy is two lines:

```
ops.ereztech.com {
    reverse_proxy localhost:8090
}
```
