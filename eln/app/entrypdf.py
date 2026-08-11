"""Render one ELN entry to a PDF, for the copy that goes to OneDrive.

The PDF is produced from `entry_print.html` — the same self-contained layout the
print dialog uses — so the archived document is the record as a person would
read it, not a machine dump.

Two deliberate differences from printing in a browser:

  * No JavaScript. `localtime.js` rewrites timestamps into the viewer's zone;
    WeasyPrint does not run scripts, so times stay as the server rendered them.
    For an archived record that is the better outcome — a fixed, unambiguous
    timestamp rather than one that depends on who opened it.
  * No network. The URL fetcher below resolves the app's own static files and
    refuses everything else, so rendering cannot hang on a webfont request and
    archiving never makes an outbound call to a third party.
"""
import os
import urllib.parse

_WEASY_ERROR = None
try:  # optional: the app must still boot if the PDF stack is unavailable
    from weasyprint import HTML, default_url_fetcher
except Exception as exc:  # pragma: no cover - depends on system libs
    HTML = None
    default_url_fetcher = None
    _WEASY_ERROR = exc


class PdfError(RuntimeError):
    pass


def available():
    return HTML is not None


def unavailable_reason():
    return str(_WEASY_ERROR) if _WEASY_ERROR else None


def _local_only_fetcher(static_dir, static_prefix="/static/"):
    """Serve the app's own static files; refuse anything remote.

    url_for('static', ...) emits root-relative paths like /static/css/style.css.
    Under a file:// base URL those resolve to the filesystem root, so they are
    remapped onto the real static directory here rather than by rewriting the
    HTML. Anything outside that directory, and anything over the network, is
    refused: rendering happens while a user waits for an archive to finish, and
    an unreachable font CDN must not be able to stall it.
    """
    static_dir = os.path.realpath(static_dir)

    def fetch(url):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme in ("http", "https"):
            raise ValueError("remote resource refused while rendering PDF: %s" % url)
        if parsed.scheme in ("file", ""):
            path = urllib.parse.unquote(parsed.path or "")
            if path.startswith(static_prefix):
                path = os.path.join(static_dir, path[len(static_prefix):])
            path = os.path.realpath(path)
            if path != static_dir and not path.startswith(static_dir + os.sep):
                raise ValueError("refused file outside the static directory: %s" % url)
            return default_url_fetcher("file://" + urllib.parse.quote(path))
        raise ValueError("refused url scheme while rendering PDF: %s" % url)

    return fetch


def render(html, static_dir):
    """HTML string -> PDF bytes."""
    if not available():
        raise PdfError(
            "PDF rendering is unavailable in this container: %s" % unavailable_reason()
        )
    doc = HTML(
        string=html,
        base_url="file://%s/" % os.path.realpath(static_dir),
        url_fetcher=_local_only_fetcher(static_dir),
    )
    return doc.write_pdf()
