# EreZtech Operations

A chemical production scheduling and R&D project management app, styled to match
ereztech.com (deep indigo `#0F0037`, orange `#F7941E`, Poppins).

## Run it

```sh
docker compose up --build
```

Then open **http://localhost:8080**.

## Sign in

Seeded accounts (all with password `ereztech` — change them after first login via **Users**):

| Username     | Role               |
|--------------|--------------------|
| `admin`      | Admin              |
| `pmanager`   | Production Manager |
| `qcmanager`  | QC Manager         |
| `rdirector`  | R&D Director       |
| `researcher1`| Researcher         |

## What's inside

**Production scheduling**
- **Calendar** — month view with runs drawn as colored duration bars (color = status).
- **Reactor Timeline** — Gantt-style view, one row per reactor, for spotting conflicts.
- **Production Runs** — each run has five reviewable aspects: Raw Materials (ordering &
  incoming QC), Procedure (R&D), Process Data & Results, QC Results, and Final Material →
  Inventory. Each aspect holds assignable links (SharePoint URLs, network paths, files),
  notes, and an approval log (approve/reject with comment, recorded against the signed-in
  user and their role).
- **Reactors** — add/remove reactors and attach free-form attributes (capacity, material,
  max temp, …). Reactors with scheduled runs can be marked inactive instead of deleted.

**R&D projects**
- **R&D Calendar** — month view drawing each project as a bar from its start date to its
  due date, **colored by assigned researcher** (each user keeps a stable color; a legend
  names them). Deliverable due dates appear as ◆ milestones. Projects without dates are
  listed under the calendar as unscheduled.
- Assignable researcher, customer, status, dates, and description.
- Assignable **project folder** link (SharePoint or network drive), plus dedicated links
  for the **Final Procedure** and **Final QC Methods**.
- Deliverables list with due dates, statuses, and links.
- Approval logs for four aspects: Project Deliverables, Final Procedure, Final QC
  Methods, and Project Completion.

**Roles & permissions (customizable)**
- Roles are data, not code: rename them, recolor them, add new ones, and set what each
  can do via permission flags (Admin / Edit production / All R&D / Own R&D) under
  **Roles** in the nav. Renames cascade to users; past approvals keep the role name in
  effect when they were signed. Six sensible defaults are seeded.
- Everyone signed in can view everything and record approvals (the approver's name,
  role, and timestamp are logged).

**Run statuses (customizable)**
- Statuses and their calendar/timeline colors are editable under **Statuses** — rename,
  recolor, add (e.g. "QC Hold"), delete unused ones. Renames cascade to runs.

**Batch linkage**
- A run can be marked as an *intermediate for* another run (set in the run form).
  Both runs then cross-link: the feeder shows what consumes it, the consumer lists its
  intermediate batches.

## Configuration

Set in `docker-compose.yml`:
- `SECRET_KEY` — change for production.
- `POSTGRES_PASSWORD` / `DATABASE_URL` — change together for production.
- App port — host port `8080` maps to the container.

Data persists in the `pgdata` Docker volume. Back up with `docker compose exec db pg_dump -U erezops erezops > backup.sql`.

## Browsing for files and folders (Doc Roots)

Link fields have a **Browse…** button that opens a folder/file picker. Because the app
runs in Docker, it can only browse folders **mounted into the container**:

1. Mount your share in `docker-compose.yml` under the app's `volumes:` — e.g. a network
   drive or OneDrive/SharePoint sync folder on the host:
   `- /Volumes/rd-share:/shares/rd`
2. As Admin, open **Doc Roots** and register it: container path `/shares/rd`, plus an
   optional **link prefix** that rewrites picked paths into what teammates should open,
   e.g. `\\fileserver\rd` or `https://ereztech.sharepoint.com/sites/RD/Shared%20Documents`.
3. Picking `Zr-ALD/Final Procedure Rev C.docx` then inserts
   `\\fileserver\rd\Zr-ALD\Final Procedure Rev C.docx` (or the SharePoint URL) into the field.

A default root ("Shares" → `/shares`, mapped from `./shares` next to the compose file)
is registered on first start with a small sample folder tree. You can still paste URLs
or paths by hand in any link field.

## Notes

- Links are stored as-is. Browsers open `https://…` links directly; UNC paths
  (`\\server\share\…`) are shown and copyable, though some browsers block navigating
  to `file://` targets from a web page by policy.
- The database schema is created automatically on first start and seeded with sample
  reactors, runs, and one R&D project so the calendar isn't empty.
