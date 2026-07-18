"""Sanitize + namespace inline SVGs (chemical structures from the sketcher).

The structure editor posts SVG straight from the browser, so a stored drawing is
untrusted input: it must be scrubbed of anything that could execute before it is
inlined into a page with ``| safe``. Ketcher's real output is only <path>/<text>/
<use>/<g>/<defs> etc., so a conservative strip of the active vectors (scripts,
event handlers, javascript: URLs) is a no-op on legitimate structures.

Namespacing then prefixes every id so several drawings inlined on one page don't
collide on shared ids (glyph-0-1, clip-0, …).
"""
import re

# paired <script>…</script> / <foreignObject>…</foreignObject> (content included)
_PAIRED = re.compile(
    r"<\s*(script|foreignObject)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL)
# any stray/self-closing script|foreignObject tag left behind
_STRAY_TAG = re.compile(r"<\s*/?\s*(?:script|foreignObject)\b[^>]*>",
                        re.IGNORECASE)
# inline event handlers: on<something>="…" / on…='…' / on…=value
_ON_ATTR = re.compile(r"\son[a-zA-Z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
                      re.IGNORECASE)
# javascript: / data:text/html in (xlink:)href — neutralize to an empty target
_JS_URI = re.compile(
    r"((?:xlink:)?href)\s*=\s*([\"'])\s*(?:javascript:|data\s*:\s*text/html)[^\"']*\2",
    re.IGNORECASE)


def sanitize_svg(svg):
    if not svg:
        return svg
    svg = _PAIRED.sub("", svg)
    svg = _STRAY_TAG.sub("", svg)
    svg = _ON_ATTR.sub("", svg)
    svg = _JS_URI.sub(r'\1=\2\2', svg)
    return svg


def namespace_svg(svg, uid):
    """Scrub the SVG, then prefix every id (and its #/url() references) with
    `uid` so multiple inlined drawings stay self-contained."""
    svg = sanitize_svg(svg)
    if not svg:
        return svg
    for i in set(re.findall(r'id="([^"]+)"', svg)):
        svg = svg.replace('id="%s"' % i, 'id="%s-%s"' % (uid, i))
        svg = svg.replace('href="#%s"' % i, 'href="#%s-%s"' % (uid, i))
        svg = svg.replace('url(#%s)' % i, 'url(#%s-%s)' % (uid, i))
    return svg
