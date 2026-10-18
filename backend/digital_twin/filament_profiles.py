import logging
"""
digital_twin/filament_profiles.py
-----------------------------------
Material property database for the extrusion model.

Properties sourced from manufacturer datasheets and published literature.
Density is the critical value for mass-based calculations (variable input shaping).
Other properties are used for flow model context and future thermal modelling.

Usage:
    from digital_twin.filament_profiles import get_profile, PROFILES

    p = get_profile("PLA")
    density = p["density_g_cm3"]   # 1.24
"""

# ── Material database ─────────────────────────────────────────────────────────
# density_g_cm3     : printed part density (slightly less than raw material
#                     due to inter-layer gaps; use 0.95× raw density as default)
# melt_temp_c       : typical print temp range [min, max]
# max_flow_mm3s     : conservative max volumetric flow for a 0.4mm nozzle
#                     (hardware and hotend dependent; used as model ceiling)
# linear_advance_k  : typical K value range [min, max] — user should calibrate
# notes             : honest caveats about model applicability

PROFILES: dict = {
    "PLA": {
        "display_name":    "PLA",
        "density_g_cm3":   1.24,
        "melt_temp_c":     [180, 230],
        "bed_temp_c":      [0, 60],
        "max_flow_mm3s":   12.0,
        "linear_advance_k": [0.02, 0.08],
        "notes": "Most predictable flow behaviour. Density varies ±0.03 by brand.",
    },
    "PLA+": {
        "display_name":    "PLA+",
        "density_g_cm3":   1.22,
        "melt_temp_c":     [200, 235],
        "bed_temp_c":      [0, 60],
        "max_flow_mm3s":   11.0,
        "linear_advance_k": [0.03, 0.09],
        "notes": "Slightly lower density than standard PLA due to impact modifiers.",
    },
    "PETG": {
        "display_name":    "PETG",
        "density_g_cm3":   1.27,
        "melt_temp_c":     [220, 250],
        "bed_temp_c":      [70, 85],
        "max_flow_mm3s":   9.0,
        "linear_advance_k": [0.04, 0.12],
        "notes": "Higher viscosity than PLA. Max flow limited by stringing risk.",
    },
    "ABS": {
        "display_name":    "ABS",
        "density_g_cm3":   1.04,
        "melt_temp_c":     [220, 260],
        "bed_temp_c":      [90, 110],
        "max_flow_mm3s":   10.0,
        "linear_advance_k": [0.03, 0.10],
        "notes": "Lower density makes it lightest common material. Warps without enclosure.",
    },
    "ASA": {
        "display_name":    "ASA",
        "density_g_cm3":   1.07,
        "melt_temp_c":     [230, 260],
        "bed_temp_c":      [90, 110],
        "max_flow_mm3s":   9.5,
        "linear_advance_k": [0.03, 0.10],
        "notes": "Similar to ABS but UV-stable. Density close to ABS.",
    },
    "TPU": {
        "display_name":    "TPU (95A)",
        "density_g_cm3":   1.21,
        "melt_temp_c":     [210, 240],
        "bed_temp_c":      [20, 60],
        "max_flow_mm3s":   4.0,
        "linear_advance_k": [0.0, 0.02],
        "notes": "Flow model limited — high elasticity makes commanded vs actual E "
                 "less reliable. Disable quality controller for TPU prints.",
    },
    "Nylon": {
        "display_name":    "Nylon (PA12)",
        "density_g_cm3":   1.15,
        "melt_temp_c":     [240, 270],
        "bed_temp_c":      [70, 90],
        "max_flow_mm3s":   8.0,
        "linear_advance_k": [0.05, 0.15],
        "notes": "Hygroscopic — density shifts noticeably when moisture-loaded. "
                 "Dry filament before printing for model accuracy.",
    },
    "PEEK": {
        "display_name":    "PEEK",
        "density_g_cm3":   1.32,
        "melt_temp_c":     [360, 400],
        "bed_temp_c":      [120, 160],
        "max_flow_mm3s":   5.0,
        "linear_advance_k": [0.06, 0.15],
        "notes": "High temp only — requires all-metal hotend. "
                 "Flow model accuracy limited by small dataset.",
    },
    "CF-PLA": {
        "display_name":    "Carbon Fibre PLA",
        "density_g_cm3":   1.29,
        "melt_temp_c":     [190, 230],
        "bed_temp_c":      [0, 60],
        "max_flow_mm3s":   8.0,
        "linear_advance_k": [0.02, 0.07],
        "notes": "CF content reduces max flow vs standard PLA. "
                 "Requires hardened nozzle — 0.4mm brass will wear rapidly.",
    },
    "CF-PETG": {
        "display_name":    "Carbon Fibre PETG",
        "density_g_cm3":   1.30,
        "melt_temp_c":     [230, 260],
        "bed_temp_c":      [70, 85],
        "max_flow_mm3s":   7.0,
        "linear_advance_k": [0.03, 0.10],
        "notes": "CF reinforced — hardened nozzle required.",
    },
    "CF-Nylon": {
        "display_name":    "Carbon Fibre Nylon",
        "density_g_cm3":   1.19,
        "melt_temp_c":     [250, 280],
        "bed_temp_c":      [70, 90],
        "max_flow_mm3s":   6.0,
        "linear_advance_k": [0.05, 0.14],
        "notes": "High strength. Hygroscopic — same moisture caution as PA12.",
    },
    "PC": {
        "display_name":    "Polycarbonate",
        "density_g_cm3":   1.20,
        "melt_temp_c":     [260, 310],
        "bed_temp_c":      [100, 120],
        "max_flow_mm3s":   6.0,
        "linear_advance_k": [0.06, 0.16],
        "notes": "Requires enclosure and high-temp hotend. Very low warping tolerance.",
    },
    "HIPS": {
        "display_name":    "HIPS",
        "density_g_cm3":   1.03,
        "melt_temp_c":     [220, 240],
        "bed_temp_c":      [90, 110],
        "max_flow_mm3s":   10.0,
        "linear_advance_k": [0.03, 0.09],
        "notes": "Common ABS support material. Lowest density in common materials.",
    },
    "PVA": {
        "display_name":    "PVA (Support)",
        "density_g_cm3":   1.23,
        "melt_temp_c":     [185, 210],
        "bed_temp_c":      [0, 45],
        "max_flow_mm3s":   6.0,
        "linear_advance_k": [0.03, 0.08],
        "notes": "Water-soluble support. Hygroscopic — degrades rapidly if not dry stored.",
    },
    "Wood-PLA": {
        "display_name":    "Wood-fill PLA",
        "density_g_cm3":   1.15,
        "melt_temp_c":     [190, 220],
        "bed_temp_c":      [0, 60],
        "max_flow_mm3s":   7.0,
        "linear_advance_k": [0.02, 0.07],
        "notes": "Wood particle fill lowers density. Prone to clogging — 0.6mm+ nozzle recommended.",
    },
    "Metal-PLA": {
        "display_name":    "Metal-fill PLA",
        "density_g_cm3":   1.70,   # varies widely by fill % and metal type
        "melt_temp_c":     [190, 220],
        "bed_temp_c":      [0, 60],
        "max_flow_mm3s":   5.0,
        "linear_advance_k": [0.02, 0.07],
        "notes": "Density varies significantly by brand (1.4–2.5 g/cm³). "
                 "Default 1.70 is a rough average. Update per-brand if accuracy matters.",
    },
}

_ALIASES = {
    "PLA_PLUS":  "PLA+",
    "NYLON":     "Nylon",
    "CARBON":    "CF-PLA",
    "CF_PLA":    "CF-PLA",
    "CF_PETG":   "CF-PETG",
    "CF_NYLON":  "CF-Nylon",
    "POLYCARBONATE": "PC",
}


def get_profile(material: str) -> dict:
    """
    Returns the filament profile for a given material name.
    Case-insensitive. Falls back to PLA if not found.
    """
    key = material.strip().upper().replace(" ", "_").replace("-", "_")
    if key in _ALIASES:
        key = _ALIASES[key].upper().replace(" ", "_").replace("-", "_")

    # Direct match
    for k, v in PROFILES.items():
        if k.upper().replace(" ", "_").replace("-", "_") == key:
            return {**v, "key": k}

    # Prefix match (e.g. "PLA_WHITE" → "PLA")
    for k, v in PROFILES.items():
        if key.startswith(k.upper().replace(" ", "_").replace("-", "_")):
            return {**v, "key": k}

    # Fallback
    logging.info(f"⚠️  Filament '{material}' not in profiles — using PLA defaults")
    return {**PROFILES["PLA"], "key": "PLA"}


def list_materials() -> list:
    """Returns list of available material keys."""
    return list(PROFILES.keys())


def get_density(material: str) -> float:
    """Convenience: returns density_g_cm3 for a material."""
    return get_profile(material)["density_g_cm3"]
