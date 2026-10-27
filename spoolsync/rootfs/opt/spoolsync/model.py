"""The common view of a spool that both sides are translated into."""

from __future__ import annotations

from dataclasses import dataclass, field

# Values that are kept equal on both sides. The order is the order of the change texts.
FIELDS = ("vendor", "material", "name", "color", "total_g", "remaining_g", "note")
WEIGHTS = ("total_g", "remaining_g")
# Two weights closer than this count as equal (both sides round differently)
WEIGHT_TOLERANCE_G = 2

LABELS = {
    "vendor": "Hersteller",
    "material": "Material",
    "name": "Bezeichnung",
    "color": "Farbe",
    "total_g": "Gesamtgewicht",
    "remaining_g": "Restgewicht",
    "note": "Notiz",
}


@dataclass
class Spool:
    id: int
    vendor: str = ""
    material: str = ""
    name: str = ""
    color: str = ""  # RRGGBB, upper case, "" = unknown
    total_g: int | None = None
    remaining_g: int | None = None
    note: str = ""
    archived: bool = False
    rfid: str = ""
    extra: dict = field(default_factory=dict)  # side specific details (slot, filament id ...)

    def values(self) -> dict:
        return {f: getattr(self, f) for f in FIELDS}

    def title(self) -> str:
        parts = [p for p in (self.vendor, self.name or self.material) if p]
        text = " ".join(parts) or "Spule"
        return f"{text} #{self.color}" if self.color else text


def type_name(name: str, material: str) -> str:
    """The filament type as the Bambu apps show it ("PLA Basic", "PETG HF").

    Spoolman names are often just a colour ("Turquoise"); then the material is the type.
    """
    name, material = (name or "").strip(), (material or "").strip()
    if not material:
        return name
    if name and material.casefold() in name.casefold():
        return name
    return material


def norm_color(value: str | None) -> str:
    """'#ffffffff', 'FFFFFF', None -> 'FFFFFF' / ''."""
    if not value:
        return ""
    text = str(value).strip().lstrip("#").upper()
    return text[:6] if len(text) >= 6 else ""


def to_grams(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def same(field_name: str, a, b) -> bool:
    """Do two values of a field mean the same?"""
    if field_name in WEIGHTS:
        if a is None or b is None:
            return a is None and b is None
        return abs(a - b) <= WEIGHT_TOLERANCE_G
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def show(field_name: str, value) -> str:
    if value is None or value == "":
        return "–"
    if field_name in WEIGHTS:
        return f"{value} g"
    if field_name == "color":
        return f"#{value}"
    return str(value)
