"""Read and write the files that make up one Ketcher structure.

KET and V3000 preserve the editor's richer representation. V2000 is retained
as a compatibility derivative for older chemistry tools.
"""
import os


def _atomic_write(path, text):
    if not text or not text.strip():
        # remove any stale sibling from a previous drawing so a re-draw can't
        # leave the bundle mixing an old structure with the new one
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return False
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def save_bundle(directory, base, v3000, v2000="", ket=""):
    os.makedirs(directory, exist_ok=True)
    saved = {"mol": _atomic_write(os.path.join(directory, base + ".mol"), v3000)}
    saved["v2000"] = _atomic_write(os.path.join(directory, base + ".v2000.mol"), v2000)
    saved["ket"] = _atomic_write(os.path.join(directory, base + ".ket"), ket)
    return saved


def load_preferred(directory, base):
    """Return KET when available, then V3000/V2000 molfile for old records."""
    for suffix in (".ket", ".mol", ".v2000.mol"):
        try:
            with open(os.path.join(directory, base + suffix), "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            pass
    return ""


def remove_bundle(directory, base):
    for suffix in (".ket", ".mol", ".v2000.mol", ".svg"):
        try:
            os.remove(os.path.join(directory, base + suffix))
        except OSError:
            pass
