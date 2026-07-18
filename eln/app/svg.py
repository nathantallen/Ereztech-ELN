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
import xml.etree.ElementTree as ET

_ALLOWED_ELEMENTS = {
    "svg", "g", "defs", "symbol", "use", "path", "line", "polyline",
    "polygon", "rect", "circle", "ellipse", "text", "tspan", "clipPath",
    "mask", "pattern", "linearGradient", "radialGradient", "stop", "title",
    "desc", "style",
}
_URI_ATTRIBUTES = {"href", "{http://www.w3.org/1999/xlink}href"}


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def sanitize_svg(svg):
    """Parse SVG as XML and remove active/unknown content and unsafe URLs."""
    if not svg:
        return svg
    try:
        root = ET.fromstring(svg)
    except (ET.ParseError, ValueError):
        return ""
    if _local_name(root.tag) != "svg":
        return ""

    def clean(parent):
        for child in list(parent):
            if _local_name(child.tag) not in _ALLOWED_ELEMENTS:
                parent.remove(child)
                continue
            clean(child)
        for attr, value in list(parent.attrib.items()):
            local = _local_name(attr).lower()
            normalized = re.sub(r"\s+", "", value or "").lower()
            if local.startswith("on"):
                del parent.attrib[attr]
            elif attr in _URI_ATTRIBUTES and not (normalized.startswith("#") or normalized == ""):
                del parent.attrib[attr]
            elif local == "style" and ("url(" in normalized or "expression(" in normalized):
                del parent.attrib[attr]
        if _local_name(parent.tag) == "style" and parent.text:
            css = re.sub(r"\s+", "", parent.text).lower()
            if "url(" in css or "@import" in css or "expression(" in css:
                parent.text = ""

    clean(root)
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    return ET.tostring(root, encoding="unicode")


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
