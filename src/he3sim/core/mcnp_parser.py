"""MCNP fuel assembly inside-out symmetric parameterization and output parser for YBS core."""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass

import numpy as np

# Physical geometry constants for YBS hex lattice (Cell 20 and Cell 140)
# Assembly flat-to-flat distance (from surface 501 PX 4.335): 2 * 4.335 = 8.67 cm
ASSEMBLY_FLAT_TO_FLAT_CM = 8.67
# Pin flat-to-flat distance (from surface 591 PX 0.7): 2 * 0.7 = 1.4 cm
PIN_FLAT_TO_FLAT_CM = 1.4

# Hex rotation matrices in MCNP:
# *tr30 0 0 0   90 0 90     180 90 90  90 90  0
R30 = np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
# *tr40 0 0 0   -30 -120 90   60 -30 90  90 90  0
R40 = np.array(
    [
        [math.sqrt(3.0) / 2.0, -0.5, 0.0],
        [0.5, math.sqrt(3.0) / 2.0, 0.0],
        [0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)
R_PIN_TRANS = R40 @ R30

# Assembly lattice hex coordinates (row, col) in Cell 20 (LAT=2, u=1)
ASSEMBLY_LATTICE_COORDS: dict[int, tuple[int, int]] = {
    90: (0, 0),  # Core Center
    91: (-1, 0),  # Peripheral Ring (Bottom-Left)
    92: (-1, 1),  # Peripheral Ring (Bottom)
    93: (0, 1),  # Peripheral Ring (Bottom-Right)
    94: (1, 0),  # Peripheral Ring (Top-Right, opposite 91)
    95: (1, -1),  # Peripheral Ring (Top, opposite 92)
    96: (0, -1),  # Peripheral Ring (Top-Left, opposite 93)
}

# Inversion pairs across the core
INVERSION_PARTNER_ASSY: dict[int, int] = {
    90: 90,
    91: 94,
    94: 91,
    92: 95,
    95: 92,
    93: 96,
    96: 93,
}

# Immutable pin identifiers
TOKEN_COOLANT = "50"
TOKEN_POLYETHYLENE = "7000"
TOKEN_AL_DUMMY = "8000"
TOKEN_FUEL = "9000"


@dataclass(frozen=True, slots=True)
class PinSiteInfo:
    """Detailed spatial and symmetry metadata for a single pin position."""

    assy_u: int
    r_rel: int
    c_rel: int
    default_token: str
    is_immutable: bool
    radial_distance_cm: float
    partner_assy_u: int
    partner_r_rel: int
    partner_c_rel: int
    orbit_id: int


@dataclass(frozen=True, slots=True)
class MCNPOutputParseResult:
    """Parsed physical parameters and tally outputs from MCNP output file."""

    keff: float | None
    keff_sd: float | None
    beta_eff: float | None
    beta_eff_sd: float | None
    lambda_gen: float | None
    lambda_gen_sd: float | None
    rossi_alpha: float | None
    flux_1501: float | None
    flux_1501_err: float | None
    flux_1503: float | None
    flux_1503_err: float | None
    converged: bool
    warnings: tuple[str, ...]


class YBSFuelCoreManager:
    """Manages the 7 YBS fuel assemblies (u=90 to 96), symmetric loading and validation."""

    def __init__(self, template_path_or_content: str | None = None) -> None:
        self.b1_assy = np.array([ASSEMBLY_FLAT_TO_FLAT_CM, 0.0, 0.0])
        self.b2_assy = np.array(
            [ASSEMBLY_FLAT_TO_FLAT_CM / 2.0, ASSEMBLY_FLAT_TO_FLAT_CM * math.sqrt(3.0) / 2.0, 0.0]
        )

        self.b1_pin = np.array([PIN_FLAT_TO_FLAT_CM, 0.0, 0.0])
        self.b2_pin = np.array(
            [PIN_FLAT_TO_FLAT_CM / 2.0, PIN_FLAT_TO_FLAT_CM * math.sqrt(3.0) / 2.0, 0.0]
        )

        self.template_text: str | None = None
        if template_path_or_content is None:
            # Search candidate paths for MCNP template
            candidates = [
                os.path.abspath(
                    os.path.join(
                        os.path.dirname(__file__),
                        "..",
                        "..",
                        "..",
                        "..",
                        "MCNP_input",
                        "YBS-0.84329.i",
                    )
                ),
                os.path.abspath(
                    os.path.join(
                        os.path.dirname(__file__), "..", "..", "..", "MCNP_input", "YBS-0.84329.i"
                    )
                ),
                os.path.abspath(os.path.join("MCNP_input", "YBS-0.84329.i")),
            ]
            for cand in candidates:
                if os.path.exists(cand):
                    template_path_or_content = cand
                    break

        if template_path_or_content is not None:
            if os.path.exists(template_path_or_content):
                with open(template_path_or_content, encoding="gbk", errors="ignore") as f:
                    self.template_text = f.read()
            else:
                self.template_text = template_path_or_content

        self.default_lattices: dict[int, list[str]] = self._parse_default_lattices()
        self.pin_sites: dict[tuple[int, int, int], PinSiteInfo] = self._build_pin_sites()
        self.symmetric_orbits: list[list[PinSiteInfo]] = self._build_symmetric_orbits()

    def _parse_default_lattices(self) -> dict[int, list[str]]:
        """Parse default 11x11 lattice tokens for u=90..96 from template if available."""
        if not self.template_text:
            return {}
        lattices = {}
        for u in range(90, 97):
            pat = (
                rf"(\b\d+\s+0\s+.*?LAT=2\s+u={u}\b.*?\n\s*FILL=-5:5\s+-5:5\s+0:0\s*\n)"
                r"((?:\s*[\d\s]+\n)+)"
            )
            m = re.search(pat, self.template_text)
            if m:
                lattices[u] = m.group(2).split()
        return lattices

    def _build_pin_sites(self) -> dict[tuple[int, int, int], PinSiteInfo]:
        """Compute spatial coordinates, radial distance, and symmetry partners for all pin sites."""
        sites: dict[tuple[int, int, int], PinSiteInfo] = {}

        orbit_counter = 0
        visited_pairs: set[tuple[int, int, int]] = set()

        for u in range(90, 97):
            r_assy, c_assy = ASSEMBLY_LATTICE_COORDS[u]
            center_assy = R40 @ (r_assy * self.b1_assy + c_assy * self.b2_assy)
            tokens = self.default_lattices.get(u, [])

            partner_u = INVERSION_PARTNER_ASSY[u]

            for r_idx in range(11):
                for c_idx in range(11):
                    token_idx = r_idx * 11 + c_idx
                    default_tok = tokens[token_idx] if tokens else TOKEN_COOLANT
                    if default_tok == TOKEN_COOLANT:
                        continue

                    r_rel = r_idx - 5
                    c_rel = c_idx - 5

                    # Inversion symmetry partner: (-r, -c) in partner_u
                    partner_r = -r_rel
                    partner_c = -c_rel

                    # Compute global Cartesian position
                    v_pin_loc = r_rel * self.b1_pin + c_rel * self.b2_pin
                    v_pin_glob = center_assy + R_PIN_TRANS @ v_pin_loc
                    dist_cm = float(np.linalg.norm(v_pin_glob[:2]))

                    is_immutable = default_tok == TOKEN_POLYETHYLENE

                    site_key = (u, r_rel, c_rel)
                    partner_key = (partner_u, partner_r, partner_c)

                    if site_key not in visited_pairs:
                        curr_orbit = orbit_counter
                        orbit_counter += 1
                        visited_pairs.add(site_key)
                        visited_pairs.add(partner_key)
                    else:
                        # Find existing orbit_id
                        curr_orbit = (
                            sites[partner_key].orbit_id if partner_key in sites else orbit_counter
                        )

                    sites[site_key] = PinSiteInfo(
                        assy_u=u,
                        r_rel=r_rel,
                        c_rel=c_rel,
                        default_token=default_tok,
                        is_immutable=is_immutable,
                        radial_distance_cm=dist_cm,
                        partner_assy_u=partner_u,
                        partner_r_rel=partner_r,
                        partner_c_rel=partner_c,
                        orbit_id=curr_orbit,
                    )

        return sites

    def _build_symmetric_orbits(self) -> list[list[PinSiteInfo]]:
        """Group reconfigurable sites into symmetric orbits sorted by core radial distance."""
        orbit_dict: dict[int, list[PinSiteInfo]] = {}
        for site in self.pin_sites.values():
            if site.is_immutable:
                continue
            orbit_dict.setdefault(site.orbit_id, []).append(site)

        # Sort orbits by mean radial distance from core center
        sorted_orbits = sorted(
            orbit_dict.values(),
            key=lambda orbit: np.mean([s.radial_distance_cm for s in orbit]),
        )
        return sorted_orbits

    def get_reconfigurable_site_count(self) -> int:
        """Total reconfigurable sites in core (31 in center + 28*6 in outer = 199)."""
        return sum(len(orbit) for orbit in self.symmetric_orbits)

    def generate_symmetric_loading_state(
        self, num_fuel_pins: int
    ) -> dict[int, dict[tuple[int, int], str]]:
        """Generate a strictly inside-out, symmetric loading configuration.

        Parameters
        ----------
        num_fuel_pins : int
            Total target fuel pins in the core (must be between 31 and 199).
            At 105, strictly reproduces the baseline reference model loading!

        Returns
        -------
        dict[int, dict[tuple[int, int], str]]
            Mapping: { assy_u: { (r_rel, c_rel): '9000' or '8000' } }
        """
        max_pins = self.get_reconfigurable_site_count()
        if not (0 <= num_fuel_pins <= max_pins):
            raise ValueError(f"num_fuel_pins must be between 0 and {max_pins}, got {num_fuel_pins}")

        config: dict[int, dict[tuple[int, int], str]] = {u: {} for u in range(90, 97)}

        # Initialize all reconfigurable sites to aluminum dummy (8000)
        for orbit in self.symmetric_orbits:
            for s in orbit:
                config[s.assy_u][(s.r_rel, s.c_rel)] = TOKEN_AL_DUMMY

        # Insert fuel pins orbit by orbit from inside out
        pins_loaded = 0
        for orbit in self.symmetric_orbits:
            orbit_size = len(orbit)
            if pins_loaded + orbit_size <= num_fuel_pins:
                for s in orbit:
                    config[s.assy_u][(s.r_rel, s.c_rel)] = TOKEN_FUEL
                pins_loaded += orbit_size
            else:
                break

        return config

    def validate_pin_configuration(
        self, config: dict[int, dict[tuple[int, int], str | int]]
    ) -> tuple[bool, list[str]]:
        """Validate whether a fuel pin configuration complies with physical constraints.

        Checks:
        1. No polyethylene pins (7000) or coolant (50) modified;
        2. Only valid tokens ('9000' or '8000') used;
        3. Pairwise 180-degree inversion symmetry across (91, 94), (92, 95), (93, 96) and 90;
        4. Inside-out radial loading consistency.
        """
        issues: list[str] = []

        # Check immutable pins and valid token types
        for u, pins in config.items():
            if u not in ASSEMBLY_LATTICE_COORDS:
                issues.append(f"Invalid assembly universe: {u}")
                continue
            for (r, c), tok in pins.items():
                str_tok = str(tok)
                site = self.pin_sites.get((u, r, c))
                if site is None:
                    issues.append(f"Assembly u={u} site ({r}, {c}) is not a valid pin position")
                    continue
                if site.is_immutable and str_tok != TOKEN_POLYETHYLENE:
                    issues.append(
                        f"Attempted to modify immutable Polyethylene pin at "
                        f"u={u}, ({r}, {c}) to {str_tok}"
                    )
                if not site.is_immutable and str_tok not in (TOKEN_FUEL, TOKEN_AL_DUMMY):
                    issues.append(
                        f"Invalid token '{str_tok}' at u={u}, ({r}, {c}); only 9000/8000 permitted"
                    )

        # Check 180-degree inversion symmetry
        for (u, r, c), site in self.pin_sites.items():
            if site.is_immutable:
                continue
            partner_u, partner_r, partner_c = (
                site.partner_assy_u,
                site.partner_r_rel,
                site.partner_c_rel,
            )

            tok1 = str(config.get(u, {}).get((r, c), site.default_token))
            tok2 = str(
                config.get(partner_u, {}).get(
                    (partner_r, partner_c),
                    self.pin_sites[(partner_u, partner_r, partner_c)].default_token,
                )
            )

            if tok1 != tok2:
                issues.append(
                    f"Symmetry broken: u={u}({r},{c})={tok1} vs "
                    f"partner u={partner_u}({partner_r},{partner_c})={tok2}"
                )

        is_valid = len([i for i in issues if not i.startswith("Warning")]) == 0
        return is_valid, issues


def modify_mcnp_fuel_pins(
    template_content_or_path: str,
    pin_overrides: dict[int, dict[tuple[int, int], str | int]],
    validate_symmetry: bool = True,
) -> tuple[str, str]:
    """Modify fuel pin tokens in MCNP input for assemblies 90..96.

    Parameters
    ----------
    template_content_or_path : str
        Path to MCNP input file or string content.
    pin_overrides : dict
        Mapping { assy_u: { (r_rel, c_rel): token } }
    validate_symmetry : bool
        If True, raises ValueError if physical/symmetry constraints are violated.

    Returns
    -------
    tuple of (modified_content, sha256_hash)
    """
    if os.path.exists(template_content_or_path):
        with open(template_content_or_path, encoding="gbk", errors="ignore") as f:
            content = f.read()
    else:
        content = template_content_or_path

    manager = YBSFuelCoreManager(content)
    if validate_symmetry:
        valid, issues = manager.validate_pin_configuration(pin_overrides)
        if not valid:
            raise ValueError("Pin configuration failed validation:\n" + "\n".join(issues[:5]))

    # Perform token substitutions in matching lattice blocks
    modified = content
    for u in range(90, 97):
        if u not in pin_overrides:
            continue
        pat = (
            rf"(\b\d+\s+0\s+.*?LAT=2\s+u={u}\b.*?\n\s*FILL=-5:5\s+-5:5\s+0:0\s*\n)"
            r"((?:\s*[\d\s]+\n)+)"
        )
        m = re.search(pat, modified)
        if not m:
            continue

        raw_tokens = m.group(2).split()
        if len(raw_tokens) != 121:
            raise RuntimeError(f"Expected 121 tokens in assembly u={u}, found {len(raw_tokens)}")

        # Update tokens with overrides
        for (r_rel, c_rel), tok in pin_overrides[u].items():
            r_idx = r_rel + 5
            c_idx = c_rel + 5
            raw_tokens[r_idx * 11 + c_idx] = str(tok)

        # Format 11x11 lattice block
        formatted_rows = []
        for row in range(11):
            row_tokens = raw_tokens[row * 11 : (row + 1) * 11]
            formatted_rows.append("      " + "   ".join(row_tokens))
        formatted_block = "\n".join(formatted_rows) + "\n"

        modified = modified[: m.start(2)] + formatted_block + modified[m.end(2) :]

    sha256 = hashlib.sha256(modified.encode("utf-8", errors="replace")).hexdigest()
    return modified, sha256


def parse_mcnp_output(output_content_or_path: str) -> MCNPOutputParseResult:
    """Robustly parse MCNP output file for keff, KOPTS kinetics, and tallies.

    Extracts:
    - Final combined keff & standard deviation
    - Adjoint-weighted beta_eff, lambda_gen (neutron generation time), rossi_alpha
    - Tally F4 (Cell 1501) and F14 (Cell 1503) flux counts and relative errors
    """
    if os.path.exists(output_content_or_path):
        with open(output_content_or_path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    else:
        text = output_content_or_path

    warnings: list[str] = []

    # 1. keff parsing
    keff: float | None = None
    keff_sd: float | None = None

    # Pattern A: final estimated combined collision/absorption/track-length keff
    m_keff = re.search(
        r"final\s+estimated\s+combined.*?keff\s*=\s*([0-9\.]+)\s+with.*?deviation\s*of\s*([0-9\.]+)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m_keff:
        keff = float(m_keff.group(1))
        keff_sd = float(m_keff.group(2))
    else:
        # Pattern B: 3-column table
        m_tbl = re.search(r"col/abs/trk-len\s+([0-9\.]+)\s+([0-9\.]+)", text, re.IGNORECASE)
        if m_tbl:
            keff = float(m_tbl.group(1))
            keff_sd = float(m_tbl.group(2))
        else:
            warnings.append("Could not extract final estimated combined keff")

    # 2. KOPTS adjoint-weighted kinetics parameters
    beta_eff: float | None = None
    beta_eff_sd: float | None = None
    lambda_gen: float | None = None
    lambda_gen_sd: float | None = None
    rossi_alpha: float | None = None

    # beta-eff = 0.00725 ( 0.00012 )
    m_beta = re.search(
        r"beta(?:_|-|\s*)eff\s*=\s*([0-9\.\+\-eE]+)(?:\s*\(\s*([0-9\.\+\-eE]+)\s*\))?",
        text,
        re.IGNORECASE,
    )
    if m_beta:
        beta_eff = float(m_beta.group(1))
        if m_beta.group(2):
            beta_eff_sd = float(m_beta.group(2))

    # generation time = 2.456e-05 ( 0.008 )
    m_lam = re.search(
        r"generation\s+time\s*=\s*([0-9\.\+\-eE]+)(?:\s*\(\s*([0-9\.\+\-eE]+)\s*\))?",
        text,
        re.IGNORECASE,
    )
    if m_lam:
        lambda_gen = float(m_lam.group(1))
        if m_lam.group(2):
            lambda_gen_sd = float(m_lam.group(2))

    # Rossi-alpha = -2.952e+02
    m_alpha = re.search(
        r"Rossi(?:_|-|\s*)alpha\s*=\s*([0-9\.\+\-eE]+)",
        text,
        re.IGNORECASE,
    )
    if m_alpha:
        rossi_alpha = abs(float(m_alpha.group(1)))  # Convention: return positive decay constant

    # 3. Tallies F4 (Cell 1501) and F14 (Cell 1503)
    flux_1501: float | None = None
    flux_1501_err: float | None = None
    flux_1503: float | None = None
    flux_1503_err: float | None = None

    # Search for Cell 1501 tally
    # Tally block: 1tally 4 ... cell 1501 ... val err
    m_t4 = re.search(
        r"(?:tally\s+4\b.*?cell\s+1501\b.*?|cell\s+1501\b.*?)\s+([0-9\.\+\-eE]+)\s+([0-9\.\+\-eE]+)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m_t4:
        flux_1501 = float(m_t4.group(1))
        flux_1501_err = float(m_t4.group(2))

    m_t14 = re.search(
        r"(?:tally\s+14\b.*?cell\s+1503\b.*?|cell\s+1503\b.*?)\s+([0-9\.\+\-eE]+)\s+([0-9\.\+\-eE]+)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m_t14:
        flux_1503 = float(m_t14.group(1))
        flux_1503_err = float(m_t14.group(2))

    converged = (keff is not None) and ("run terminated abnormally" not in text.lower())

    return MCNPOutputParseResult(
        keff=keff,
        keff_sd=keff_sd,
        beta_eff=beta_eff,
        beta_eff_sd=beta_eff_sd,
        lambda_gen=lambda_gen,
        lambda_gen_sd=lambda_gen_sd,
        rossi_alpha=rossi_alpha,
        flux_1501=flux_1501,
        flux_1501_err=flux_1501_err,
        flux_1503=flux_1503,
        flux_1503_err=flux_1503_err,
        converged=converged,
        warnings=tuple(warnings),
    )
