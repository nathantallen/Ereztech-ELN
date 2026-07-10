# EreZtech Operations

Chemical production scheduling + R&D project management web app for EreZtech
(organometallics manufacturer, ereztech.com). Flask + PostgreSQL, runs entirely
in Docker.

## Run / develop

- `docker compose up --build` → http://localhost:8090 (login `admin` / `ereztech` on a fresh DB)
- Schema is created and seeded automatically at container start (`app/init_db.py`);
  additive migrations live in its `migrate()`. There is no Alembic — add
  `ALTER TABLE ... IF NOT EXISTS` statements there for schema changes.
- After code changes: `docker compose build app && docker compose up -d app`.
  Data persists in the `pgdata` volume.
- Machine-specific browse mounts go in `docker-compose.override.yml` (gitignored,
  see `.example`). Server deployment lives in `deploy/` (see `deploy/DEPLOY.md`).

## Architecture

- `app/__init__.py` — app factory; context processor injects `is_admin`,
  `can_edit_prod`, `status_colors`, `role_colors` into all templates.
- Blueprints: `main` (calendar + reactor Gantt), `runs` (production runs, 5 approval
  stages each), `reactors`, `rd` (R&D projects + researcher-colored calendar),
  `admin` (users), `settings` (editable Roles + RunStatus tables), `docroots`
  (Browse-dialog roots), `auth`.
- Permissions are flag-based via the `roles` table (`app/permissions.py`), NOT
  hardcoded role names. Users/runs reference roles/statuses by NAME; renames cascade
  via UPDATE. Approval records snapshot the role name at signing time (audit trail —
  never rewrite them).
- Links to documents are stored as text (SharePoint URLs, UNC paths). The Browse…
  dialog (`app/static/js/filebrowser.js` + `docroots.py`) walks folders mounted
  under the container and maps picks through each Doc Root's link prefix.

## Conventions

- Branding: indigo `#0F0037`, orange `#F7941E`, lavender `#dad0ec`, Poppins font,
  orange Z in the wordmark ("Ere<span class=z>Z</span>tech").
- Server-rendered Jinja templates, plain CSS in `app/static/css/style.css`
  (CSS variables at top), no JS framework. Forms POST + redirect + flash.
- Deletion guards everywhere: users with approvals can't be deleted (disable
  instead), reactors with runs can't be deleted (deactivate), statuses/roles in
  use can't be deleted.
