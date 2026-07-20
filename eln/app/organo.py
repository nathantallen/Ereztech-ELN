"""Company-wide starter structures for common organometallic drawing tasks."""

BUILTIN_ORGANOMETALLIC_TEMPLATES = [
    {"key": "tmga", "name": "Trimethylgallium", "group": "Precursors",
     "structure": "C[Ga](C)C"},
    {"key": "tma", "name": "Trimethylaluminum", "group": "Precursors",
     "structure": "C[Al](C)C"},
    {"key": "dez", "name": "Diethylzinc", "group": "Precursors",
     "structure": "CC[Zn]CC"},
    {"key": "cp", "name": "Cyclopentadienyl", "group": "Ligands",
     "structure": "[cH-]1cccc1"},
    {"key": "acac", "name": "Acetylacetonate", "group": "Ligands",
     "structure": "CC(=O)C=C(C)[O-]"},
    {"key": "amidinate", "name": "Amidinate", "group": "Ligands",
     "structure": "C[N-]C(=N)C"},
    {"key": "carbonyl", "name": "Carbonyl ligand", "group": "Ligands",
     "structure": "[C-]#[O+]"},
]

for _symbol in ("Ga", "Al", "Zn", "In", "Mg", "Li", "Fe", "Co", "Ni",
                "Cu", "La", "Ce", "Nd", "Gd", "Hf", "Ta", "W"):
    BUILTIN_ORGANOMETALLIC_TEMPLATES.append({
        "key": "metal-" + _symbol.lower(),
        "name": _symbol,
        "group": "Metal atoms",
        "structure": "[%s]" % _symbol,
    })


def available_templates(storage):
    builtins = [dict(item, builtin=True) for item in BUILTIN_ORGANOMETALLIC_TEMPLATES]
    return builtins + storage.get_structure_templates()
