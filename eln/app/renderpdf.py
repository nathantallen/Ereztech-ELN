"""Render every notebook entry to PDF, for the copies that go to OneDrive.

Run inside the container:

    python -m app.renderpdf <outdir> [<cachedir>]

Writes `<outdir>/<page-ref>.pdf` for every entry that has a chemist/notebook/page
reference, and prints one `<page-ref> <author>` line per file so the caller knows
where each belongs.

Content-addressed cache
-----------------------
The printed record carries a "Generated <timestamp>" line, so re-rendering an
unchanged entry produces *different bytes* every time. Without a cache the hourly
backup would re-upload every PDF on every run and fill the superseded folder with
identical documents. So each entry is fingerprinted from its `entry.md` plus the
names, sizes and mtimes of its files; an unchanged fingerprint reuses the cached
PDF byte-for-byte, and rclone then correctly skips it.
"""
import hashlib
import os
import shutil
import sys

from flask import render_template
from flask_login import login_user

from . import archive, entrypdf
from . import create_app, User


def _fingerprint(entry_dir):
    h = hashlib.sha256()
    md = os.path.join(entry_dir, "entry.md")
    if os.path.isfile(md):
        with open(md, "rb") as f:
            h.update(f.read())
    for dirpath, dirs, files in os.walk(entry_dir):
        dirs.sort()
        for name in sorted(files):
            if name in (".archived.json",) or name.endswith(".tmp"):
                continue
            p = os.path.join(dirpath, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            h.update(os.path.relpath(p, entry_dir).encode())
            h.update(b"%d:%d" % (st.st_size, int(st.st_mtime)))
    return h.hexdigest()


def main(outdir, cachedir=None):
    os.makedirs(outdir, exist_ok=True)
    if cachedir:
        os.makedirs(cachedir, exist_ok=True)

    if not entrypdf.available():
        print("ERROR: PDF rendering unavailable: %s" % entrypdf.unavailable_reason(),
              file=sys.stderr)
        return 1

    app = create_app()
    storage = app.extensions["storage"]
    from . import entries as E

    rendered = cached = skipped = failed = 0
    for meta in storage.list_entries():
        eid = meta["id"]
        label = archive.page_ref(meta)
        if not label:
            skipped += 1          # no page reference: nothing correct to call it
            continue

        entry_dir = storage.entry_dir(eid)
        target = os.path.join(outdir, "%s.pdf" % label)
        fp = _fingerprint(entry_dir)
        cache_pdf = os.path.join(cachedir, "%s.pdf" % label) if cachedir else None
        cache_fp = os.path.join(cachedir, "%s.fp" % label) if cachedir else None

        if cache_pdf and os.path.isfile(cache_pdf) and os.path.isfile(cache_fp):
            if open(cache_fp).read().strip() == fp:
                shutil.copyfile(cache_pdf, target)
                print("%s %s" % (label, meta.get("author") or ""))
                cached += 1
                continue

        try:
            author = storage.find_user(meta.get("author")) or {}
            with app.test_request_context():
                if author:
                    login_user(User(author))
                ctx = E._print_context(eid)
                # Honest attribution: nobody pressed print, the backup did.
                ctx["generated_by"] = "Automated backup"
                html = render_template("entry_print.html", **ctx)
            pdf = entrypdf.render(html, app.static_folder)
        except Exception as exc:                      # one bad entry must not
            print("ERROR %s: %s" % (eid, exc), file=sys.stderr)   # stop the rest
            failed += 1
            continue

        with open(target, "wb") as f:
            f.write(pdf)
        if cache_pdf:
            shutil.copyfile(target, cache_pdf)
            with open(cache_fp, "w") as f:
                f.write(fp)
        print("%s %s" % (label, meta.get("author") or ""))
        rendered += 1

    print("rendered=%d cached=%d skipped_no_page_ref=%d failed=%d"
          % (rendered, cached, skipped, failed), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
