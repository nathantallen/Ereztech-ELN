"""Inventory units and compatibility helpers.

Balances are stored in one canonical unit per dimension (g, mL, or mmol), while
users can enter and report quantities in the most convenient compatible unit.
Legacy batches with a free-text ``quantity`` such as ``250 g`` are normalized
on read so existing installations continue to work without a destructive
migration.
"""
import re


UNIT_DEFINITIONS = {
    "mg": ("mass", 0.001, "g"),
    "g": ("mass", 1.0, "g"),
    "kg": ("mass", 1000.0, "g"),
    "µL": ("volume", 0.001, "mL"),
    "mL": ("volume", 1.0, "mL"),
    "L": ("volume", 1000.0, "mL"),
    "mmol": ("amount", 1.0, "mmol"),
    "mol": ("amount", 1000.0, "mmol"),
}

UNITS_BY_FAMILY = {
    "mass": ["mg", "g", "kg"],
    "volume": ["µL", "mL", "L"],
    "amount": ["mmol", "mol"],
}

_UNIT_ALIASES = {
    "mg": "mg", "g": "g", "kg": "kg",
    "ul": "µL", "μl": "µL", "µl": "µL",
    "ml": "mL", "l": "L",
    "mmol": "mmol", "mol": "mol",
}


def normalize_unit(unit):
    raw = str(unit or "").strip()
    if raw in UNIT_DEFINITIONS:
        return raw
    return _UNIT_ALIASES.get(raw.lower(), raw)


def unit_family(unit):
    definition = UNIT_DEFINITIONS.get(normalize_unit(unit))
    return definition[0] if definition else None


def units_for(unit_or_family):
    family = unit_or_family if unit_or_family in UNITS_BY_FAMILY else unit_family(unit_or_family)
    return list(UNITS_BY_FAMILY.get(family, []))


def to_base(value, unit):
    unit = normalize_unit(unit)
    if unit not in UNIT_DEFINITIONS:
        raise ValueError("Unsupported inventory unit: %s" % (unit or "blank"))
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("Enter a numeric inventory quantity.")
    if number < 0:
        raise ValueError("Inventory quantities cannot be negative.")
    family, multiplier, base_unit = UNIT_DEFINITIONS[unit]
    return number * multiplier, base_unit, family


def from_base(value, unit):
    unit = normalize_unit(unit)
    if unit not in UNIT_DEFINITIONS:
        raise ValueError("Unsupported inventory unit: %s" % (unit or "blank"))
    return float(value) / UNIT_DEFINITIONS[unit][1]


def _number(value):
    text = ("%.9f" % float(value)).rstrip("0").rstrip(".")
    return text or "0"


def format_quantity(value, unit):
    return "%s %s" % (_number(value), normalize_unit(unit))


def format_base(value, base_unit, preferred_unit=None):
    unit = normalize_unit(preferred_unit)
    if unit not in UNIT_DEFINITIONS or UNIT_DEFINITIONS[unit][2] != base_unit:
        unit = base_unit
    return format_quantity(from_base(value, unit), unit)


def parse_legacy_quantity(text):
    match = re.fullmatch(
        r"\s*([0-9]+(?:\.[0-9]+)?|\.[0-9]+)\s*(mg|g|kg|[uµμ]l|ml|l|mmol|mol)\s*",
        str(text or ""), re.I)
    if not match:
        return None
    unit = normalize_unit(match.group(2))
    base_value, base_unit, family = to_base(match.group(1), unit)
    return {
        "value": float(match.group(1)), "unit": unit, "family": family,
        "base_value": base_value, "base_unit": base_unit,
    }


def batch_quantity(meta):
    """Return a normalized quantity snapshot for new or legacy batch metadata."""
    base_value = meta.get("quantity_base")
    base_unit = normalize_unit(meta.get("quantity_base_unit"))
    display_unit = normalize_unit(meta.get("quantity_unit"))
    try:
        base_value = float(base_value)
    except (TypeError, ValueError):
        base_value = None
    if base_value is not None and base_value >= 0 and base_unit in ("g", "mL", "mmol"):
        family = unit_family(base_unit)
        if unit_family(display_unit) != family:
            display_unit = base_unit
        return {
            "value": from_base(base_value, display_unit), "unit": display_unit,
            "family": family, "base_value": base_value, "base_unit": base_unit,
            "display": format_base(base_value, base_unit, display_unit),
        }
    parsed = parse_legacy_quantity(meta.get("quantity", ""))
    if parsed:
        parsed["display"] = format_quantity(parsed["value"], parsed["unit"])
        return parsed
    return {"value": 0.0, "unit": "g", "family": "mass",
            "base_value": 0.0, "base_unit": "g", "display": "0 g"}


def set_batch_quantity(meta, base_value, base_unit, preferred_unit=None):
    base_value = max(0.0, float(base_value))
    base_unit = normalize_unit(base_unit)
    if base_unit not in ("g", "mL", "mmol"):
        raise ValueError("Invalid canonical inventory unit.")
    unit = normalize_unit(preferred_unit)
    if unit_family(unit) != unit_family(base_unit):
        unit = base_unit
    value = from_base(base_value, unit)
    meta["quantity_base"] = round(base_value, 12)
    meta["quantity_base_unit"] = base_unit
    meta["quantity_value"] = round(value, 12)
    meta["quantity_unit"] = unit
    meta["quantity"] = format_quantity(value, unit)  # backward-compatible display
    return meta
