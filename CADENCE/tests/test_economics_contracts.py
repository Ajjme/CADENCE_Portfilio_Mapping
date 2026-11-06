import pytest
from pydantic import ValidationError

from cadence.economics.contracts import (
    AssetEconomicsInput,
    EconomicsRunConfig,
    InstalledCostOverride,
)


def _override(cost: float = 10.0) -> dict:
    return {
        "installed_usd_per_sqft": cost,
        "material_share": 0.6,
        "labor_share": 0.4,
    }


def _config() -> dict:
    return {
        "installed_cost_overrides": {
            "OFFICIAL_ASPHALT": _override(8.0),
            "OFFICIAL_METAL": _override(12.0),
            "OFFICIAL_TILE": _override(15.0),
        },
        "default_roof_shape": "gable",
        "default_roof_deck_attachment": "8d_6in_12in",
        "default_roof_wall_connection": "strap",
    }


def test_accepts_default_economics_config() -> None:
    config = EconomicsRunConfig.model_validate(_config())

    assert config.start_year == 2026
    assert config.end_year == 2050
    assert config.installed_cost_overrides["OFFICIAL_TILE"].installed_usd_per_sqft == 15.0


def test_accepts_later_start_and_shorter_horizon() -> None:
    config = EconomicsRunConfig.model_validate(
        {**_config(), "start_year": 2030, "end_year": 2040,
         "real_discount_rate": 0.035, "scghg_discount_rate": 2.5}
    )

    assert (config.start_year, config.end_year) == (2030, 2040)
    assert config.real_discount_rate == 0.035
    assert config.scghg_discount_rate == 2.5


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start_year", 2025),
        ("end_year", 2051),
        ("real_discount_rate", -0.01),
        ("scghg_discount_rate", 3.0),
        ("enabled_cost_streams", ["material", "unknown"]),
    ],
)
def test_rejects_invalid_run_configuration(field: str, value: object) -> None:
    values = _config()
    values[field] = value

    with pytest.raises(ValidationError):
        EconomicsRunConfig.model_validate(values)


def test_rejects_reversed_horizon() -> None:
    with pytest.raises(ValidationError, match="economics horizon"):
        EconomicsRunConfig.model_validate(
            {**_config(), "start_year": 2040, "end_year": 2030}
        )


def test_requires_all_three_installed_cost_overrides() -> None:
    values = _config()
    del values["installed_cost_overrides"]["OFFICIAL_TILE"]

    with pytest.raises(ValidationError, match="exactly Asphalt, Metal, and Tile"):
        EconomicsRunConfig.model_validate(values)


def test_requires_override_shares_to_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="must sum to 1"):
        InstalledCostOverride(
            installed_usd_per_sqft=10.0,
            material_share=0.8,
            labor_share=0.3,
        )


def test_rejects_nonpositive_roof_area() -> None:
    with pytest.raises(ValidationError):
        AssetEconomicsInput(
            asset_id="A-1",
            current_roof_type="asphalt",
            roof_area_sqft=0.0,
            input_roof_age=5,
            zip_code="29401",
            cbsa_code="16700",
            state_code="SC",
            county_fips="45019",
            labor_market_id="16700",
        )