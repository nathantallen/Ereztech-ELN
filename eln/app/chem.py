"""Chemistry helpers: molecular weight / formula from V2000/V3000 molfiles, and a
local, human-editable physical-properties database (data/properties.json).

Implicit hydrogens follow standard organic valence rules; metals and any
element not in the valence table get none (correct for organometallics drawn
with explicit alkyl groups, e.g. TMGa as Ga with three CH3 carbons).
"""
import json
import os
import re
import threading

# Reentrant so learn() can hold the lock across load+append+save while save()
# re-acquires it (a plain Lock would deadlock on that nested acquire).
_LOCK = threading.RLock()

ATOMIC_WEIGHTS = {
    "H": 1.008, "He": 4.0026, "Li": 6.94, "Be": 9.0122, "B": 10.81, "C": 12.011,
    "N": 14.007, "O": 15.999, "F": 18.998, "Ne": 20.180, "Na": 22.990, "Mg": 24.305,
    "Al": 26.982, "Si": 28.085, "P": 30.974, "S": 32.06, "Cl": 35.45, "Ar": 39.95,
    "K": 39.098, "Ca": 40.078, "Sc": 44.956, "Ti": 47.867, "V": 50.942, "Cr": 51.996,
    "Mn": 54.938, "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38,
    "Ga": 69.723, "Ge": 72.630, "As": 74.922, "Se": 78.971, "Br": 79.904, "Kr": 83.798,
    "Rb": 85.468, "Sr": 87.62, "Y": 88.906, "Zr": 91.224, "Nb": 92.906, "Mo": 95.95,
    "Tc": 98.0, "Ru": 101.07, "Rh": 102.91, "Pd": 106.42, "Ag": 107.87, "Cd": 112.41,
    "In": 114.82, "Sn": 118.71, "Sb": 121.76, "Te": 127.60, "I": 126.90, "Xe": 131.29,
    "Cs": 132.91, "Ba": 137.33, "La": 138.91, "Ce": 140.12, "Pr": 140.91, "Nd": 144.24,
    "Sm": 150.36, "Eu": 151.96, "Gd": 157.25, "Tb": 158.93, "Dy": 162.50, "Ho": 164.93,
    "Er": 167.26, "Tm": 168.93, "Yb": 173.05, "Lu": 174.97, "Hf": 178.49, "Ta": 180.95,
    "W": 183.84, "Re": 186.21, "Os": 190.23, "Ir": 192.22, "Pt": 195.08, "Au": 196.97,
    "Hg": 200.59, "Tl": 204.38, "Pb": 207.2, "Bi": 208.98, "Th": 232.04, "U": 238.03,
}

DEFAULT_VALENCE = {"H": 1, "B": 3, "C": 4, "N": 3, "O": 2, "F": 1, "Si": 4,
                   "P": 3, "S": 2, "Cl": 1, "Br": 1, "I": 1}

# old-style molfile charge column -> charge
_OLD_CHARGE = {1: 3, 2: 2, 3: 1, 5: -1, 6: -2, 7: -3}


def parse_molfile(text):
    """Return (atoms, bonds): atoms = [{'symbol', 'charge'}], bonds = [(a1, a2, order)].
    Raises ValueError on malformed input."""
    lines = text.splitlines()
    if len(lines) < 4:
        raise ValueError("molfile too short")
    if "V3000" in lines[3] or any(line.startswith("M  V30 BEGIN CTAB") for line in lines):
        return _parse_v3000(lines)
    counts = lines[3]
    try:
        natoms, nbonds = int(counts[0:3]), int(counts[3:6])
    except ValueError:
        raise ValueError("bad counts line")
    atoms, bonds = [], []
    for i in range(natoms):
        line = lines[4 + i]
        symbol = line[31:34].strip()
        charge = 0
        try:
            charge = _OLD_CHARGE.get(int(line[36:39]), 0)
        except (ValueError, IndexError):
            pass
        atoms.append({"symbol": symbol, "charge": charge})
    for i in range(nbonds):
        line = lines[4 + natoms + i]
        a1, a2, order = int(line[0:3]), int(line[3:6]), int(line[6:9])
        bonds.append((a1 - 1, a2 - 1, order))
    for line in lines[4 + natoms + nbonds:]:
        if line.startswith("M  CHG"):
            fields = line.split()
            n = int(fields[2])
            for k in range(n):
                idx, chg = int(fields[3 + 2 * k]) - 1, int(fields[4 + 2 * k])
                if 0 <= idx < natoms:
                    atoms[idx]["charge"] = chg
        elif line.startswith("M  END"):
            break
    return atoms, bonds


def _parse_v3000(lines):
    """Parse the atom/bond subset needed for formula and molecular weight.

    Ketcher uses V3000 for structures that V2000 cannot faithfully represent,
    including coordinate bonds and richer organometallic drawings. Coordinate
    and hydrogen bonds do not consume the donor atom's normal covalent valence.
    """
    atoms, bonds = [], []
    section = None
    for raw in lines:
        if not raw.startswith("M  V30 "):
            continue
        line = raw[7:].strip()
        if line == "BEGIN ATOM":
            section = "atom"
            continue
        if line == "END ATOM":
            section = None
            continue
        if line == "BEGIN BOND":
            section = "bond"
            continue
        if line == "END BOND":
            section = None
            continue
        fields = line.split()
        if section == "atom" and len(fields) >= 2:
            symbol = fields[1]
            charge = 0
            for field in fields[5:]:
                if field.startswith("CHG="):
                    try:
                        charge = int(field[4:])
                    except ValueError:
                        pass
            atoms.append({"symbol": symbol, "charge": charge})
        elif section == "bond" and len(fields) >= 4:
            try:
                bond_type = int(fields[1])
                a1, a2 = int(fields[2]) - 1, int(fields[3]) - 1
            except ValueError:
                continue
            # MDL 9 = coordination and 10 = hydrogen bond. Neither contributes
            # to ordinary valence/implicit-H calculation on the donor ligand.
            order = 0 if bond_type in (9, 10) else bond_type
            bonds.append((a1, a2, order))
    if not atoms:
        raise ValueError("V3000 atom block missing")
    return atoms, bonds


def formula_and_mw(molfile):
    """Compute (hill_formula, mw) for the first molecule in a molfile.
    Returns (None, None) if it cannot be parsed."""
    try:
        atoms, bonds = parse_molfile(molfile)
    except (ValueError, IndexError):
        return None, None
    if not atoms:
        return None, None
    order_sum = [0.0] * len(atoms)
    for a1, a2, order in bonds:
        o = 1.5 if order == 4 else float(order)
        if 0 <= a1 < len(atoms):
            order_sum[a1] += o
        if 0 <= a2 < len(atoms):
            order_sum[a2] += o
    counts = {}
    for i, atom in enumerate(atoms):
        sym = atom["symbol"]
        if sym not in ATOMIC_WEIGHTS:  # query atom, R-group etc.
            return None, None
        counts[sym] = counts.get(sym, 0) + 1
        val = DEFAULT_VALENCE.get(sym)
        if val is not None:
            # A positive charge raises the available valence of electronegative
            # p-block atoms (NH4+ from N+), but LOWERS it for group-14 centres
            # where a formal charge means a missing bond, not an extra H (R3C+ is
            # trivalent). Using val+charge for carbon invented phantom hydrogens.
            charge = atom["charge"]
            if sym in ("C", "Si"):
                eff_valence = val - abs(charge)
            else:
                eff_valence = val + charge
            implicit = max(0, int(round(eff_valence - order_sum[i])))
            if implicit:
                counts["H"] = counts.get("H", 0) + implicit
    mw = sum(ATOMIC_WEIGHTS[s] * n for s, n in counts.items())
    # Hill order: C, H, then alphabetical when carbon is present; otherwise
    # every element is alphabetical (so CuH3N, not H3CuN).
    parts = []
    order = (["C", "H"] + sorted(k for k in counts if k not in ("C", "H"))
             if counts.get("C") else sorted(counts))
    for sym in order:
        if counts.get(sym):
            parts.append(sym + (str(counts[sym]) if counts[sym] > 1 else ""))
    return "".join(parts), round(mw, 2)


# ---------- PubChem lookup (best-effort, silent offline) ----------

CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


def pubchem_lookup(smiles, timeout=4):
    """Resolve a drawn structure to {'cas', 'name'} via PubChem synonyms.
    Returns {} on any failure (offline labs must not be disrupted)."""
    if not smiles:
        return {}
    try:
        import requests
        r = requests.post(
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/synonyms/JSON",
            data={"smiles": smiles}, timeout=timeout)
        r.raise_for_status()
        info = r.json()["InformationList"]["Information"][0]
        synonyms = info.get("Synonym", [])
    except Exception:
        return {}
    out = {}
    for syn in synonyms:
        if CAS_RE.match(syn.strip()):
            out["cas"] = syn.strip()
            break
    if synonyms:
        out["name"] = synonyms[0]
    return out


# ---------- physical properties database ----------

SEED_PROPERTIES = [
    {"name": "Tetrahydrofuran", "cas": "109-99-9", "formula": "C4H8O", "mw": 72.11,
     "density": 0.889, "bp_c": 66, "mp_c": -108, "source": "seed"},
    {"name": "Diethyl ether", "cas": "60-29-7", "formula": "C4H10O", "mw": 74.12,
     "density": 0.706, "bp_c": 34.6, "mp_c": -116, "source": "seed"},
    {"name": "n-Hexane", "cas": "110-54-3", "formula": "C6H14", "mw": 86.18,
     "density": 0.659, "bp_c": 69, "mp_c": -95, "source": "seed"},
    {"name": "Pentane", "cas": "109-66-0", "formula": "C5H12", "mw": 72.15,
     "density": 0.626, "bp_c": 36, "mp_c": -130, "source": "seed"},
    {"name": "Toluene", "cas": "108-88-3", "formula": "C7H8", "mw": 92.14,
     "density": 0.867, "bp_c": 111, "mp_c": -95, "source": "seed"},
    {"name": "Dichloromethane", "cas": "75-09-2", "formula": "CH2Cl2", "mw": 84.93,
     "density": 1.325, "bp_c": 40, "mp_c": -97, "source": "seed"},
    {"name": "Trimethylgallium", "cas": "1445-79-0", "formula": "C3H9Ga", "mw": 114.83,
     "density": 1.151, "bp_c": 55.7, "mp_c": -15.8, "source": "seed"},
    {"name": "Trimethylaluminum", "cas": "75-24-1", "formula": "C3H9Al", "mw": 72.09,
     "density": 0.752, "bp_c": 125, "mp_c": 15, "source": "seed"},
    {"name": "Diethylzinc", "cas": "557-20-0", "formula": "C4H10Zn", "mw": 123.53,
     "density": 1.205, "bp_c": 117, "mp_c": -28, "source": "seed"},
    {"name": "Triethylgallium", "cas": "1115-99-7", "formula": "C6H15Ga", "mw": 156.91,
     "density": 1.058, "bp_c": 143, "mp_c": -82.3, "source": "seed"},
    {"name": "Gallium trichloride", "cas": "13450-90-3", "formula": "Cl3Ga", "mw": 176.07,
     "density": 2.47, "bp_c": 201, "mp_c": 77.9, "source": "seed"},
    {"name": "Methylmagnesium chloride (3.0 M in THF)", "cas": "676-58-4",
     "formula": "CH3ClMg", "mw": 74.79, "density": 1.014, "source": "seed"},
]


class PropertyDB:
    def __init__(self, path):
        self.path = path

    def ensure(self):
        if not os.path.exists(self.path):
            self.save(SEED_PROPERTIES)

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f).get("properties", [])
        except (OSError, ValueError):
            return []

    def save(self, props):
        with _LOCK:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"properties": props}, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)

    def lookup(self, cas=None, name=None, formula=None):
        props = self.load()
        cas = (cas or "").strip()
        name = (name or "").strip().lower()
        formula = (formula or "").strip()
        if cas:
            for p in props:
                if p.get("cas") == cas:
                    return p
        if name:
            for p in props:
                if p.get("name", "").lower() == name:
                    return p
            for p in props:
                if name and name in p.get("name", "").lower():
                    return p
        if formula:
            for p in props:
                if p.get("formula") == formula:
                    return p
        return None

    def learn(self, record):
        """Add a user-entered record if we don't already know this substance."""
        if not record.get("name") and not record.get("cas"):
            return
        # Hold the lock across the whole read-modify-write so two concurrent
        # saves can't each load the same list, append, and clobber the other.
        with _LOCK:
            if self.lookup(cas=record.get("cas"), name=record.get("name")):
                return
            props = self.load()
            record["source"] = "user"
            props.append(record)
            self.save(props)
