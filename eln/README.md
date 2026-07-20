# Ereztech Electronic Lab Notebook

An electronic lab notebook (ELN) for air-sensitive organometallic synthesis,
built for Ereztech's electronics-precursor R&D and production labs. Runs as a
single Docker image; all records are stored as **human-readable files** in a
storage location you assign (NAS share, SharePoint-synced folder, or local disk).

## Features

- **Notebook entries** with structured sections (Objective, Procedure,
  Observations & Data, Results & Conclusions), Markdown formatting,
  atmosphere/technique field (N₂/Ar glovebox, Schlenk line, …) and tags.
- **Built-in chemical structure editor** ([Ketcher](https://github.com/epam/ketcher),
  bundled — works offline). Structures are saved as `.mol` files with a rendered
  SVG and SMILES string alongside.
- **Reaction setup & stoichiometry** — define the reaction by drawing each
  component; molecular weight and formula are calculated from the structure,
  and density / b.p. are looked up from a local, self-learning properties
  database (`data/properties.json`). Set the scale (mg → kg, or mmol/mol) of
  the limiting component and every mass, volume and theoretical yield updates
  live, formatted in grams or kilograms as appropriate.
- **Lab operations mode** — a "Start lab work" button starts the run timer;
  every observation, photo and recording is stamped with wall-clock time *and*
  elapsed time (t+HH:MM:SS) in an append-only `observations.md`. A "Finish &
  save observation" button timestamps and stores each note. End of work is
  recorded the same way, and a signed entry can't be produced while work is
  still running.
- **Home Assistant cameras & sensors, grouped by lab hood** — an admin assigns
  each hood its cameras and sensors (temperature, pressure, or custom
  entities). An entry picks its hood, camera and sensors during setup, with a
  live MJPEG preview and selectable recording frame rate / resolution.
  During the run: one-click photo capture, start/stop MP4 recording (ffmpeg in
  the container), and continuous sensor logging to per-entity CSVs plotted
  live in a compact strip at the top of the page — expandable to full screen.
- **Raw material batch recording** — materials catalog (CAS, formula, hazards,
  air-sensitivity, storage requirements) with per-lot batch records (purity,
  container, location, status) and Certificate-of-Analysis attachments. Entries
  can allocate one component across several lots. Starting Actions and
  Observations deducts the allocations; ending requires consumed, recovered and
  returned reconciliation. Compatible mass, volume and amount units are
  normalized, and every balance change is written to the inventory ledger and
  the experiment audit trail.
- **Data file attachments** — attach video (inline playback), sensor logs
  (CSV/TSV with inline preview), spectra, images or any other file to an entry.
- **Sign & witness workflow** — drafts are editable; signing (with password
  confirmation) locks the entry; a second scientist witnesses it. Every entry
  carries an append-only `audit.log`.
- **Users & customizable roles** — administrators can create roles with their
  own name, color, notebook-edit access, and administration access. Users are
  disabled, never deleted, so signatures stay valid.

## Quick start

```bash
cd eln
docker compose up --build
```

Open http://localhost:8091. A fresh data directory uses these credentials:

```text
Username: admin
Password: ereztech
```

Change the default password under **Users** immediately after signing in.
Existing installations retain their current administrator password.

## Assigning the storage location

Everything the ELN writes lives under one directory, mounted at `/data` in the
container. Point it wherever you want the notebook to live:

```bash
# Local folder (default): ./data next to docker-compose.yml
docker compose up

# NAS share already mounted on the host
ELN_DATA_DIR=/mnt/nas/lab-notebook docker compose up -d

# SharePoint / OneDrive-synced folder on the host
ELN_DATA_DIR="$HOME/Ereztech/Shared Documents/Lab Notebook" docker compose up -d
```

To mount an SMB/NAS share directly on a Linux host first:

```bash
sudo mount -t cifs //nas.ereztech.local/lab-notebook /mnt/nas/lab-notebook \
  -o credentials=/etc/smb-eln.cred,uid=$(id -u),file_mode=0664,dir_mode=0775
```

For SharePoint, sync the document library to the host with OneDrive and point
`ELN_DATA_DIR` at the synced folder; the notebook's plain-text files then index
and preview naturally in SharePoint.

## Storage format (human-readable)

```
data/
├─ users.json                    accounts & roles (hashed passwords)
├─ properties.json               physical-properties DB (seeded, self-learning)
├─ equipment.json                Home Assistant URL/token + hood assignments
├─ structure_templates.json      company-wide Ketcher templates
├─ inventory_transactions.jsonl  append-only inventory ledger
├─ notebook/
│  └─ ELN-2026-0001/
│     ├─ entry.md                YAML frontmatter (incl. reaction & stoichiometry,
│     │                          equipment, run times) + Markdown sections
│     ├─ observations.md         append-only timestamped operational log
│     ├─ audit.log               append-only event history
│     ├─ structures/             authoritative .ket/.mol V3000, V2000 compatibility
│     │                          files, and .svg renders
│     ├─ sensors/                one CSV per logged sensor entity
│     ├─ photos/                 camera snapshots taken during the run
│     ├─ recordings/             MP4 camera recordings
│     └─ attachments/            uploaded videos, sensor logs, spectra, …
└─ materials/
   └─ trimethylgallium/
      ├─ material.md             catalog record
      ├─ batches/tmg-2606-a.md   one file per lot
      └─ attachments/            certificates of analysis
```

The files are the system of record — no database. Back up, diff, index or read
them directly from the share without this application.

## Configuration

| Variable            | Default        | Purpose                                   |
|---------------------|----------------|-------------------------------------------|
| `ELN_DATA_DIR`      | `./data`       | Host folder mounted as the notebook store |
| `ELN_SECRET_KEY`    | generated      | Flask session key (persisted in `/config`) |
| `ELN_MAX_UPLOAD_MB` | `512`          | Maximum attachment size (MB)              |
| `ELN_HA_URL`        | —              | Home Assistant URL (or set via Equipment page) |
| `ELN_HA_TOKEN`      | —              | HA long-lived access token (or via Equipment page) |

## Home Assistant setup

1. In the ELN as an admin, open **Equipment** and sign in with a Home
   Assistant username and password (e.g. `http://homeassistant.local:8123`).
   The ELN runs HA's own login flow server-side: the password is exchanged
   for a refresh token and **never stored**; short-lived access tokens are
   refreshed automatically. Alternatively, expand *"…or use a long-lived
   access token"* and paste a token (required if the HA account uses
   multi-factor authentication).
2. Once *connected*, the page lists every `camera.*` and `sensor.*` entity.
   Add your lab hoods and tick the cameras/sensors installed in each one
   (custom entities can be added by id). Entries then choose their equipment
   per hood; all HA credentials stay server-side (camera streams are proxied).

### Demo without a real Home Assistant

```bash
docker compose --profile demo up --build -d
```

starts `mock_ha/` — a stand-in serving two hood cameras (animated synthetic
frames) and four sensors (smooth synthetic signals). Point Equipment at
`http://mockha:8123` with any token.

## Development

```bash
cd eln
docker compose up --build          # rebuild after code changes
```

The image bundles Ketcher 3.17.0 (Apache-2.0) under `app/static/ketcher/`.
The ELN adds a touch/full-screen mode, local unsaved-sketch recovery, built-in
organometallic starter templates, and administrator-managed company templates.
Drawings are preserved as KET and V3000 with V2000 compatibility exports.
