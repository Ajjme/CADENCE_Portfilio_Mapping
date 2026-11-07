# Precomputed reference files

Small versions of the large raw inputs. The app reads these instead of the raw
files, which keeps each run's memory low and keeps the raw data out of every
Streamlit boot. `manifest.json` records what each file was built from.

| File | Built from | Used for |
| --- | --- | --- |
| `wind_return_periods.parquet` | `Data/Wind_Return_Periods/gev_return_periods.csv` | Each asset's nearest wind grid cell and gust return levels |
| `zcta_county_cbsa.parquet` | NHGIS block-to-ZCTA and block-to-CBSA crosswalks | Each ZIP's county and CBSA |
| `zcta_boundaries_lookup.parquet` | TIGER 2020 ZCTA shapefile, simplified by about 11 m | Finding the ZIP each asset falls in |
| `zcta_boundaries_map.parquet` | TIGER 2020 ZCTA shapefile, simplified like the map always was | The ZIP / ZCTA results map |
| `fragility_curves.parquet` | `Data/Fragility_Curves/iecc2021` (1,440 files) | Every terrain-averaged fragility curve |

## Where the raw files are

The raw files are no longer on `main`. Every Streamlit boot used to download all
of them (about 9 GB), even though runs only need these small files. They are kept
at the `raw-data-v1` tag, and Git LFS still stores them.

## Rebuilding these files

Do this when a raw input changes, like when new wind results replace
`gev_return_periods.csv`.

1. From the repository root, restore the raw files (Git LFS downloads about 9 GB):

   ```
   git restore --source raw-data-v1 -- CADENCE/Data/Fragility_Curves/iecc2021 CADENCE/Data/Wind_Return_Periods/gev_return_periods.csv CADENCE/Data/Geography/Census_TIGER/raw/v2020/tl_2020_us_zcta520.zip CADENCE/Data/Geography/IPUMS_NHGIS/raw/v2020/nhgis_blk2010_cbsa2020.zip CADENCE/Data/Geography/IPUMS_NHGIS/raw/v2020/nhgis_blk2010_zcta2020/nhgis_blk2010_zcta2020.csv
   ```

   `.gitignore` keeps them out of commits, so they stay on your computer only.

2. Swap in any new raw file, then from the `CADENCE` folder run:

   ```
   python -m cadence.reference_data.precompute
   ```

   Add `--only wind` (or `zip_lookup`, `zip_boundaries`, `fragility`) to rebuild one file.

3. Commit the updated files in this folder.

A new raw file also needs a new tag (`raw-data-v2`) so the next rebuild can find it.
