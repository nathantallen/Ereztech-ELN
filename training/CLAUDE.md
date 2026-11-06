# Ereztech Chemical Safety Training

Training app for the Saukville chemical safety program (video playlist with
role-based tracks, server-scored quiz, sign + verify training records). Flask +
a **file-based** store (no database), runs in Docker. Separate from `../eln/`
and the parent operations app, but follows the ELN's conventions.

## Run / develop

- `docker compose up --build` → http://localhost:8092. A fresh data folder seeds
  `admin` / `ereztech` and copies the curriculum from `app/content/`.
- Tests: `python -m unittest tests/test_training.py` (from `training/`).
- Rebuild after code changes: `docker compose build training && docker compose up -d training`.

## Architecture

- `app/__init__.py` — app factory, `User` (role flags `can_admin`, `can_verify`),
  CSRF (token injected into every POST form), mutation lock, `markdown`,
  `nicedate` and `day` filters.
- Blueprints: `auth` (login + rate limit, My password), `main` (My Training
  dashboard), `playlist` (parts, video pages, mark watched), `quiz` (take, score,
  review attempts), `records` (matrix, CSV, per-person record, sign / verify /
  return), `admin` (users + tracks, roles, settings).
- `storage.py` — the file store (layout in its docstring). Curriculum YAML is
  hot-reloaded by mtime.
- `progress.py` — pure status rules: tracks → required videos, the current
  cycle (since the last verified record), quiz scoring, status keys.

## Conventions

- Branding and CSS match the ELN: indigo `#0F0037`, orange `#F7941E`, lavender
  `#dad0ec`, Poppins. `static/css/style.css` starts as a copy of the ELN's;
  training-only rules are at the end. Server-rendered Jinja, vanilla JS
  (`static/js/training.js` only adds the nav toggle and quiz counter).
  Forms POST + redirect + flash.
- Timestamps are stored in UTC and shown in the lab timezone (Settings).
- Quiz answers never go to the browser before submission (`quiz._public`).
- Never rewrite verified records, `watched.jsonl`, `attempts.jsonl` or `audit.log`.
  Records are returned (with a reason), never deleted. Users are disabled, never
  deleted. The verifier must be a different person from the trainee.
- Site rules (EEOP/CHP) live in `playlist.yaml` (`site_rule`, part `notes`) and as
  `site:` tags on quiz questions; where a site rule and a video differ, the site
  rule is the answer.
