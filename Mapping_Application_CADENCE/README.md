# Mapping Application Prototype

`mapping_interface.py` is the original visual and interaction prototype for the CADENCE portfolio map. It is retained as a design reference only and contains non-authoritative prototype RUL and ranking calculations.

The production three-page application now lives under `CADENCE/src/cadence/ui`. It uses the official Asphalt, Metal, and Tile terminology and delegates all vulnerability, lifecycle, and economic calculations to the existing CADENCE pipelines.

From the `CADENCE` directory, install and launch it with:

```shell
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[ui,geo,test]'
bash run_dashboard.sh
```

Use http://localhost:8520/ for the combined dashboard; do not launch this prototype as another dashboard server.

The default input is `CADENCE/Data/User_Inputs/asset_inventory_test_1.xlsx`. Uploaded workbooks are stored separately and never overwrite that repository input.