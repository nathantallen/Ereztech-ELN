# EreZtech ELN — CasaOS source transfer

Source revision: `e6f22d8`

This folder contains the complete source needed to build the ELN image directly
on an Intel/AMD64 CasaOS server. It intentionally contains no notebook data,
passwords, camera credentials, Docker volumes, or local environment files.

## 1. Copy this folder to CasaOS

Copy the complete folder to a persistent location, for example:

```text
/DATA/AppData/ereztech-eln/source
```

The bundled Ketcher structure editor is large, so make sure the `app/static/ketcher`
folder finishes transferring.

## 2. Build and start

Open a CasaOS terminal, change to the transferred folder, and run:

```bash
docker compose build eln
docker compose up -d eln
```

Open:

```text
http://CASAOS-SERVER-IP:8091
```

## 3. Find the first-run administrator password

For a new empty data directory:

```bash
docker compose logs eln
```

Look for the generated `admin` password and store it securely.

## Persistent data

By default, notebook files are stored in `./data` beside this source folder and
the small location/secret configuration is stored in the Docker volume
`eln_config`. Back up both. To use explicit CasaOS paths, create a `.env` file:

```dotenv
ELN_DATA_DIR=/DATA/AppData/ereztech-eln/data
ELN_NAS_DIR=/DATA/AppData/ereztech-eln/nas
ELN_MAX_UPLOAD_MB=512
```

Create those directories before starting the container. Do not put `.env` into
source control if it later contains secrets.

## Updating later

Stop the app, replace only the source files, then rebuild. Preserve the data
directory and `eln_config` volume:

```bash
docker compose build --no-cache eln
docker compose up -d eln
```

## Verification

```bash
docker compose ps
docker compose logs --tail=100 eln
```

The `eln` service should report `Up` and listen on port `8091`.
