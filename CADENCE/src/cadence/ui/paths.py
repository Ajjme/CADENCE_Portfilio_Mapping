"""Repository paths used by the local CADENCE UI."""

from pathlib import Path

CADENCE_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = CADENCE_ROOT / "Data"
DEFAULT_WORKBOOK = DATA_ROOT / "User_Inputs" / "asset_inventory_test_1.xlsx"
ECONOMICS_CONFIG = DATA_ROOT / "User_Inputs" / "economics_config_test_1.json"
WIND_RETURN_PERIODS = DATA_ROOT / "Wind_Return_Periods" / "gev_return_periods.csv"
CLIMATE_ZONES = DATA_ROOT / "Climate_Zones" / "ClimateZones.shp"
FRAGILITY_ROOT = DATA_ROOT / "Fragility_Curves" / "iecc2021"
CLIMATE_DELTA = DATA_ROOT / "Climate_Delta" / "wind_climate_scaling.parquet"
RESULTS_ROOT = CADENCE_ROOT / "cadence_datalake" / "results"
ALTERNATIVE_RESULTS_ROOT = RESULTS_ROOT / "roof_alternative_analysis"
UI_WORK_ROOT = CADENCE_ROOT / "cadence_datalake" / "streamlit_sessions"
MAPPING_ROOT = CADENCE_ROOT / "Data_Catalogs" / "Mapping"
MATERIAL_MAPPING = MAPPING_ROOT / "master_mapping_reference_draft.csv"
MATERIAL_CLASS_MAP = MAPPING_ROOT / "official_material_class_map_v1.csv"