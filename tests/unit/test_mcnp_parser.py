"""Unit tests for MCNP fuel assembly inside-out symmetric parameterization and output parser."""

from __future__ import annotations

import os

from he3sim.core.mcnp_parser import (
    TOKEN_AL_DUMMY,
    TOKEN_FUEL,
    TOKEN_POLYETHYLENE,
    YBSFuelCoreManager,
    modify_mcnp_fuel_pins,
    parse_mcnp_output,
)

TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "MCNP_input", "YBS-0.84329.i"
)


def test_fuel_core_manager_geometry() -> None:
    assert os.path.exists(TEMPLATE_PATH), f"Template not found at {TEMPLATE_PATH}"
    manager = YBSFuelCoreManager(TEMPLATE_PATH)

    # 7 assemblies * 37 pins = 259 total pin positions
    assert len(manager.pin_sites) == 259

    # Reconfigurable sites = 199 (31 in assembly 90, 28 in each of 91..96)
    assert manager.get_reconfigurable_site_count() == 199

    # Polyethylene pins = 60 (6 in 90, 9 in each of 91..96)
    pe_pins = [s for s in manager.pin_sites.values() if s.is_immutable]
    assert len(pe_pins) == 60
    assert all(s.default_token == TOKEN_POLYETHYLENE for s in pe_pins)

    # Verify radial hierarchy: inner fuel < PE moderator < outer dummy
    inner_fuel = [
        s
        for s in manager.pin_sites.values()
        if s.assy_u in range(91, 97) and s.default_token == TOKEN_FUEL
    ]
    pe_sites = [
        s
        for s in manager.pin_sites.values()
        if s.assy_u in range(91, 97) and s.default_token == TOKEN_POLYETHYLENE
    ]
    outer_al = [
        s
        for s in manager.pin_sites.values()
        if s.assy_u in range(91, 97) and s.default_token == TOKEN_AL_DUMMY
    ]

    mean_r_fuel = sum(s.radial_distance_cm for s in inner_fuel) / len(inner_fuel)
    mean_r_pe = sum(s.radial_distance_cm for s in pe_sites) / len(pe_sites)
    mean_r_al = sum(s.radial_distance_cm for s in outer_al) / len(outer_al)

    assert mean_r_fuel < mean_r_pe < mean_r_al


def test_baseline_symmetry_validation() -> None:
    manager = YBSFuelCoreManager(TEMPLATE_PATH)

    # Validate that baseline template itself satisfies 180-degree inversion symmetry
    default_config: dict[int, dict[tuple[int, int], str]] = {u: {} for u in range(90, 97)}
    for (u, r, c), site in manager.pin_sites.items():
        default_config[u][(r, c)] = site.default_token

    is_valid, issues = manager.validate_pin_configuration(default_config)
    assert is_valid, f"Baseline configuration broke symmetry: {issues}"


def test_generate_symmetric_loading_state() -> None:
    manager = YBSFuelCoreManager(TEMPLATE_PATH)

    # Test generating 105 fuel pins (the baseline count)
    config_105 = manager.generate_symmetric_loading_state(num_fuel_pins=105)
    is_valid, issues = manager.validate_pin_configuration(config_105)
    assert is_valid, f"Generated 105-pin state is invalid: {issues}"

    # Count loaded fuel pins
    loaded_fuel = sum(
        1 for assy in config_105.values() for tok in assy.values() if tok == TOKEN_FUEL
    )
    # Plus PE pins (which are not in reconfigurable dict)
    assert loaded_fuel == 105

    # Test subcritical 60 pins
    config_60 = manager.generate_symmetric_loading_state(num_fuel_pins=60)
    is_valid, issues = manager.validate_pin_configuration(config_60)
    assert is_valid, f"Generated 60-pin state is invalid: {issues}"


def test_immutable_pin_protection() -> None:
    manager = YBSFuelCoreManager(TEMPLATE_PATH)

    # Find a PE pin position in assembly 91: (-2, 0)
    pe_site = manager.pin_sites[(91, -2, 0)]
    assert pe_site.is_immutable

    # Attempt to illegally replace PE pin with fuel pin
    illegal_config = {
        91: {(-2, 0): TOKEN_FUEL},
    }
    is_valid, issues = manager.validate_pin_configuration(illegal_config)
    assert not is_valid
    assert any("immutable Polyethylene pin" in msg for msg in issues)


def test_modify_mcnp_fuel_pins() -> None:
    manager = YBSFuelCoreManager(TEMPLATE_PATH)
    config_sym = manager.generate_symmetric_loading_state(num_fuel_pins=105)

    modified_text, sha256 = modify_mcnp_fuel_pins(TEMPLATE_PATH, config_sym, validate_symmetry=True)

    assert isinstance(sha256, str) and len(sha256) == 64
    assert "KCODE 1e4 1.0 150 1150" in modified_text
    assert "F4:N 1501" in modified_text
    assert "F14:N 1503" in modified_text
    assert "NORTH SAFETY ROD SYSTEM" in modified_text


def test_parse_mcnp_output() -> None:
    sample_output = """
    MCNP Version 6.2
    run terminated normally

    final estimated combined collision/absorption/track-length
    keff = 0.84329 with an estimated standard deviation of 0.00045

    * * * * * * * * * * * * * * * * adjoint-weighted kinetics parameters
    * * * * * * * * * * * * * * * *
    beta-eff =  0.00725  ( 0.00012 )
    prompt neutron lifetime = 2.012e-05 ( 0.006 )
    neutron generation time = 2.456e-05 ( 0.008 )
    Rossi-alpha = -2.952e+02 ( 0.010 )

    1tally        4   nps =     10000000
    cell  1501
      1.23456E-04 0.0034

    1tally       14   nps =     10000000
    cell  1503
      2.34567E-04 0.0042
    """

    res = parse_mcnp_output(sample_output)

    assert res.converged is True
    assert res.keff == 0.84329
    assert res.keff_sd == 0.00045
    assert res.beta_eff == 0.00725
    assert res.beta_eff_sd == 0.00012
    assert res.lambda_gen == 2.456e-05
    assert res.lambda_gen_sd == 0.008
    assert res.rossi_alpha == 295.2  # positive magnitude
    assert res.flux_1501 == 1.23456e-04
    assert res.flux_1501_err == 0.0034
    assert res.flux_1503 == 2.34567e-04
    assert res.flux_1503_err == 0.0042
