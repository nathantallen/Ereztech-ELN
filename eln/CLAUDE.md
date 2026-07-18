# EreZtech Electronic Lab Notebook (ELN)

An electronic lab notebook for air-sensitive organometallic synthesis (EreZtech
makes electronics-industry organometallic precursors — MOCVD/ALD sources like
TMGa, TMA, DEZ). Flask + a **file-based** store (no database), runs entirely in
Docker. This `eln/` project is separate from the parent `erezops/` operations app.

## Run / develop

- `docker compose up --build` → http://localhost:8091. A fresh store generates
  an `admin` password and prints it once in `docker compose logs eln`. Rebuild
  after code changes: `docker compose build eln && docker compose up -d eln`.
- **Offline / home development:** `docker compose --profile demo up --build` also
  starts `mock_ha/` — a stand-in Home Assistant at `http://mockha:8123` serving
  fake hood cameras + sensors, plus a **Digest-auth Amcrest-style camera** at
  `/cgi-bin/snapshot.cgi` and `/cgi-bin/mjpg/video.cgi` (creds `cam_user`/`cam_pass`).
  Use this at home — the real Home Assistant and cameras are only reachable on the
  lab network. In the app: Equipment → sign in to HA with URL `http://mockha:8123`
  and any username/password (mock accepts `demo`/`demo`), or add an IP camera
  pointing at the mock's CGI URLs.
- On a fresh machine the `eln_config` Docker volume is empty, so there's no stored
  storage-location pointer → it defaults to `./data` (bind mount) and seeds a fresh
  notebook with a generated admin password. That's the intended home-dev state.
- If Ketcher fails to load: it's vendored under `app/static/ketcher/` (EPAM
  Ketcher 3.17, Apache-2.0, ~115 MB). It ships in the repo; no build step.

## Architecture

- `app/__init__.py` — app factory. Context processor injects `is_admin`,
  `can_edit`, `status_colors`, `role_colors`, `timezone`, `storage_fallback`.
  `nicedate` filter emits `<time class="lt">` (localized client-side). A
  `before_request` **maintenance gate** 503s mutating requests during a storage
  relocation.
- Blueprints: `auth`, `main` (dashboard + Storage/settings + storage browse/relocate
  + timezone), `entries` (experiments), `materials` (catalog + batches + structures),
  `admin` (users), `equipment` (Home Assistant + IP cameras grouped by lab hood).
- `storage.py` — the file store. Entries live in **per-user lab books**:
  `notebook/<username>/ELN-YYYY-NNNN/`. `entry_dir(eid)` locates an entry by scanning
  user folders (cached); `save_entry` places it by `meta.author`. Also: techniques,
  app settings (timezone), materials/batches, observations, sensor CSVs.
- `ha.py` — Home Assistant client (username/password login flow → refresh token, or
  long-lived token), **camera layer** (HA `camera.*` proxy + direct IP cameras with
  Digest/Basic auth, RTSP via ffmpeg, HTTP MJPEG), background **sensor pollers** and
  **camera recording** (RTSP-direct or snapshot-poll → ffmpeg mp4).
- `chem.py` — molecular weight/formula from a V2000 molfile, self-learning physical-
  properties DB (`properties.json`), PubChem CAS lookup (best-effort, silent offline).
- `location.py` — assignable data location: browse allowed roots, `switch()` copies
  the store to a new folder (or adopts an existing one), pointer persisted in
  `/config` (the `eln_config` volume) so it survives restarts.
- `seed.py` — first-run admin user + example materials/entry.

## Data layout (all human-readable, the files ARE the notebook)

```
<data>/                          # /data by default, or a relocated NAS/SharePoint folder
  users.json  properties.json  techniques.json  settings.json  equipment.json
  notebook/<username>/ELN-2026-0001/
    entry.md            # YAML frontmatter (reaction, stoichiometry, equipment,
                        # operations times) + Markdown sections
    observations.md     # append-only, timestamped operational log
    audit.log           # append-only event history
    structures/  sensors/  photos/  recordings/  attachments/
  materials/<slug>/material.md  batches/<lot>.md  structure.mol|.svg  attachments/
```

## Conventions

- Branding: indigo `#0F0037`, orange `#F7941E`, lavender `#dad0ec`, Poppins,
  orange Z in the wordmark. Server-rendered Jinja, plain CSS in
  `app/static/css/style.css` (CSS variables at top), vanilla JS (no framework).
  Forms POST + redirect + flash.
- **Timestamps are stored in UTC**; displayed in the configured lab timezone
  (Storage page) or the viewer's local time if unset. Never render raw UTC to users.
- Permissions: `admin` / `scientist` (can edit) / `viewer`. Entries are drafts until
  **signed** (password-confirmed, locks content) then **witnessed** (different user).
  Never rewrite signed/witnessed records or audit logs.
- Verify UI changes in the browser, not just curl. There's a Docker rebuild between
  code changes; static/template changes sometimes need `--no-cache` if a new file
  isn't picked up.

## Current state & known issues (2026-07)

- **Cameras:** the real Amcrest (`Lab 120-1`, `10.70.50.29`) is on a subnet the
  lab container can't route to, and RTSP :554 is blocked; only HTTP :80 (Digest CGI)
  is the viable path there. Code supports Digest auth, RTSP-via-ffmpeg, HTTP MJPEG,
  and a snapshot-refresh live-preview fallback — all verified against the mock. To
  actually use the Amcrest, add it to Home Assistant (reachable) and select the
  `camera.*` entity, or make its subnet routable. Develop camera features against
  the demo mock at home.
- **Storage:** in the lab it was relocated to the NAS at `/nas/eln-notebook`; the old
  copy at `/data` is retained. At home you won't have the NAS — expect the default
  `./data` store and the demo mock.
- Relocation is refused while any experiment run is active (quiesce first).
- Not yet done: HTTPS (LAN/VPN only for now), tests, and `eln/` had no prior git
  history before this snapshot.
