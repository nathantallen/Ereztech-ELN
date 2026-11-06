# Ereztech Chemical Safety Training

A training app for the Saukville chemical safety program: the 11-part video
playlist with role-based tracks, key points for every video, a 55-question quiz
scored on the server, and a sign-off workflow that produces a permanent training
record. Same stack and conventions as the ELN (`../eln`): Flask, server-rendered
Jinja, plain CSS, vanilla JS, a **file-based** store, one Docker image.

## Quick start

```bash
cd training
docker compose up --build
```

Open http://localhost:8092 and sign in:

```text
Username: admin
Password: ereztech
```

Change the password under **My password** (click your name) right away.

## How training works

1. **Tracks.** Everyone takes **Core**. An administrator adds role tracks per
   person under **Users** (Air-sensitive, Scale-up, HF, Drums & cylinders, Waste,
   Respirator users, First-aid responders, Confined space).
2. **Watch.** Trainees open each assigned video from **Playlist** (YouTube plays
   inline; Vimeo and Berkeley Lab links open in a new tab), read the key points
   and any site rule (EEOP/CHP), and click **Mark as watched**.
3. **Quiz.** The quiz is scored on the server — answers never reach the browser
   before submission. Every attempt is saved. Pass mark: 80%.
4. **Sign.** With all assigned videos watched and a passing attempt, the trainee
   signs the record (statement + password). This creates `TRN-YYYY-NNNN`.
5. **Verify.** A trainer (a different person) verifies it with their password,
   or returns it with a reason. Verified records are permanent.
6. **Retrain.** A verified record stays current for 12 months (Settings). After
   that the person shows as Overdue and starts a new cycle: videos watched and
   attempts taken before the last verification don't count toward the next one.

**Records** (trainers and admins) shows everyone's status — Overdue, Awaiting
verification, Ready to sign, Due soon, In progress, Not started, Current — with a
CSV download.

## Roles

| Role | Can |
|---|---|
| Administrator | Everything: users, roles, tracks, settings, verify records |
| Trainer | See everyone's records, verify or return signed records |
| Trainee | Complete their own training and see their own record |

Roles are data (`roles.json`), editable under **Users → New role**, with two
permission flags: *can verify* and *can administer*. Users are disabled, never
deleted, so signatures stay valid.

## Storage (human-readable)

```
data/
├─ users.json            accounts, roles, assigned tracks (hashed passwords)
├─ roles.json            role names, colors, permission flags
├─ settings.json         retraining interval, due-soon window, lab timezone
├─ curriculum/
│  ├─ playlist.yaml      parts, tracks, videos, key points, site rules
│  └─ quiz.yaml          questions, options, answer letters, explanations
└─ records/<username>/
   ├─ watched.jsonl      append-only: one line per "marked watched"
   ├─ attempts.jsonl     append-only: one line per scored quiz attempt
   ├─ completions/TRN-2026-0001.md   signed / verified record (YAML frontmatter)
   └─ audit.log          append-only event history
```

The files are the system of record — back them up, diff them, or read them
straight from the share without the app.

### Changing the curriculum

Edit `data/curriculum/playlist.yaml` or `quiz.yaml` on the share; the app picks
up the change on the next page view. Keep video `id`s stable once people have
watched them. When questions change, bump the quiz `version` so earlier attempts
stay labelled with the version they were scored against. A fresh data folder is
seeded from `app/content/`.

## Configuration

| Variable              | Default     | Purpose                                     |
|-----------------------|-------------|---------------------------------------------|
| `TRAINING_DATA_DIR`   | `./data`    | Host folder mounted as the training store   |
| `TRAINING_SECRET_KEY` | generated   | Flask session key (persisted in the data folder) |

To keep records on the NAS or a SharePoint-synced folder:

```bash
TRAINING_DATA_DIR=/mnt/nas/safety-training docker compose up -d
```

## Development

```bash
cd training
pip install -r requirements.txt
python -m unittest tests/test_training.py      # 15 tests
TRAINING_DATA_DIR=./data flask --app app:create_app run --port 8092
```
