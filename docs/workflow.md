# CANCO2-Storage Workflow

This document describes the implemented Bronze, Silver, and unified-atlas
workflow. Each source is acquired, harmonized, validated, and published as an
independent Silver package. The completed unified build then maps those
packages into canonical tables while preserving source lineage and semantic
distinctions.

## Layers

### Bronze

Bronze is the retained source layer under `data/raw/<dataset_id>/`. Acquisition
modules download official source files, preserve provider directory structures,
extract archives where required, and validate expected source products. Existing
completed downloads are reused unless the source module is run with
`--overwrite`. Bronze files are not modified by Silver processing.

Shared acquisition behavior includes streamed downloads, temporary `.part`
files, retry handling, ZIP path validation, and SHA-256 hashing where a source
workflow requests it. Source-specific validation remains in the corresponding
acquisition module.

### Silver

Silver products are written under `data/processed/<dataset_id>/`. A harmonizer
reads Bronze data, validates source schema and identifiers, maps fields into a
source-specific canonical output, repairs invalid geometries in memory, and
reprojects spatial layers to EPSG:3978 (NAD83 / Canada Atlas Lambert).

Before completion, the harmonizer reopens the written GeoPackage. Persisted
spatial layers are checked for:

- the expected CRS;
- unchanged feature counts and stable unique identifiers;
- no null or empty geometries; and
- valid geometries after GeoPackage serialization.

Metadata and QA are stored in the GeoPackage as registered `attributes` tables.
Source schema inventories, metadata summaries, QA summaries, field dictionaries,
and dataset README files are emitted as sidecar files when that dataset
workflow implements them.

### Unified atlas

The unified build reads the four dated Silver GeoPackages under
`data/processed/` and writes a dated GeoPackage under
`data/processed/unified_storage/`. It also reads the Statistics Canada
province/territory boundary dataset acquired by the Bronze workflow to subset
NATCARB saline and coal grid cells to Canada.

The unified GeoPackage contains four canonical tables:

| Table | Grain or role |
| --- | --- |
| `storage_units` | One logical geological storage unit |
| `storage_features` | One spatial representation of a storage unit |
| `storage_assessments` | Capacity, prospectivity, and related assessment records |
| `administrative_features` | Regulatory and tenure features kept separate from geological storage objects |

Unified metadata, QA, source catalog, and complete precursor metadata and QA
lineage are persisted in additional registered attribute tables. The unified
README and sidecar inventories are generated from the persisted GeoPackage.
The [researcher quickstart](quickstart.md) is the recommended first-five-minutes
workflow and reads this GeoPackage directly without creating a second database
or pre-aggregated capacity artifact.

## Registered datasets

The four geological datasets currently registered in both orchestration layers
are:

| ID | Bronze source | Silver classification |
| --- | --- | --- |
| `aer_agreements` | Alberta Energy Regulator Carbon Sequestration Agreements | Regulatory tenure; no capacity data |
| `gbc_ne_atlas` | Geoscience BC Northeast BC Geological Carbon Capture and Storage Atlas | Quantitative geological storage screening |
| `gsc_atlantic` | Geological Survey of Canada Open File 8996 | Qualitative geological prospectivity / Chance of Success |
| `natcarb_doe` | DOE/NETL NATCARB All Data v1502 | Quantitative geological storage resource |

The orchestration registries define the processing order. Supplying dataset IDs
in another order does not change that order.

`statcan_digital_boundaries` is registered for Bronze acquisition as a support
dataset for the unified build. It is not a Silver storage package.

## Commands

Run commands from the repository root using the active Python 3.12-or-newer
environment.

Install the package in editable mode:

```bash
python -m pip install -e .
```

The complete installed workflow is:

```bash
canco2-build
```

This runs Bronze acquisition, all four Silver workflows, the unified atlas,
and unified README generation. The script equivalent is
`python scripts/build_all.py`.

Acquire all Bronze sources:

```bash
python scripts/run_bronze.py
```

Acquire selected sources. The `--dataset` option may be repeated:

```bash
python scripts/run_bronze.py --dataset gsc_atlantic
python scripts/run_bronze.py --dataset aer_agreements --dataset gbc_ne_atlas
```

Build all Silver packages:

```bash
python scripts/run_silver.py
```

Build a selected Silver package:

```bash
python scripts/run_silver.py --dataset natcarb_doe
```

Run the complete Bronze-then-Silver pipeline:

```bash
python scripts/build_geopackages.py
```

Build the unified atlas from the completed precursor GeoPackages:

```bash
python scripts/build_unified.py
```

Run the complete workflow, including the precursor GeoPackages followed by the
unified atlas:

```bash
python scripts/build_all.py
```

The top-level builder accepts one or more dataset IDs and can run either layer:

```bash
python scripts/build_geopackages.py --datasets gsc_atlantic natcarb_doe
python scripts/build_geopackages.py --skip-bronze
python scripts/build_geopackages.py --skip-silver
```

`--skip-bronze` assumes the required Bronze inputs already exist. `--skip-silver`
performs acquisition only. Passing both skip options is rejected.

For source inspection without writing Silver outputs, the GSC Atlantic, AER,
and BC harmonizers support `--inspect-only`:

```bash
python -m canco2_storage.harmonize.gsc_atlantic --inspect-only
python -m canco2_storage.harmonize.aer_agreements --inspect-only
python -m canco2_storage.harmonize.gbc_ne_atlas --inspect-only
```

## Dataset-specific processing

### AER agreements

The source CRS is expected to be EPSG:3400. The Silver package preserves one
feature per source agreement tract in `aer_agreement_tracts` and creates a
validated agreement-level dissolve in `aer_agreements`. Agreement-level
attribute consistency is checked before dissolving. The product is regulatory
and tenure information, not capacity, injectivity, or prospectivity.

### Northeast BC atlas

Appendix C supplies logical pool and aquifer records; Appendix E supplies the
published spatial layers. Pool records are linked to the canonical master pool
shapefile, while aquifers are reconciled to the published aquifer shapefiles.
Source-native estimates and discrepancy flags are retained. A logical unit may
have multiple spatial features, so feature counts must not be summed as
capacity.

### GSC Atlantic

The harmonizer validates and combines 15 Open File 8996 shapefiles into one
`storage_units` layer. Reservoir, seal, trap, and total Chance of Success
attributes remain prospectivity measures. They are not quantitative storage
capacity or injectivity estimates.

### NATCARB

The harmonizer preserves five source representations as separate layers and
retains ten provider domain tables. It does not remove provider duplicate or
overlap flags, aggregate overlapping resources, merge grid and polygon
representations, clip to Canada, or infer missing properties. See
`schema.md` for the layer contract.

### Unified atlas

The unified harmonizer preserves source-derived identifiers and records the
precursor dataset and layer for every canonical row. It separates logical
storage units, spatial representations, and assessments so spatial feature
counts cannot silently become capacity multipliers. AER regulatory and tenure
polygons are written to `administrative_features`, separate from geological
storage objects.

Run the GeoPackage-first researcher example after a unified build:

```bash
python examples/unified_quickstart.py
```

## Reproducibility and interpretation

Output filenames use the generated-date convention
`YYYYMMDD_13_DataType_AV`. The harmonizer chooses the run date once and writes
it into the persisted metadata table. README generation reads that persisted
date, rather than using the current clock, when reconstructing sidecar
filenames. A later run therefore creates a new dated product instead of
overwriting an earlier artifact, while all documentation for one artifact
uses one pinned date.

This is reproducible-by-pinned-inputs, not a promise of byte-identical rebuilds:
the source archive/workbook/GDB version, run date, Python and geospatial
dependency versions, and output environment must be pinned for an exact rebuild.
The current workflow preserves source checksums where acquisition provides
them, but does not yet enforce byte-level artifact hashes.

The Silver and unified products are screening and source-preservation
artifacts. They do not assign P10/P50/P90 scenarios across datasets, estimate
injectivity, select project-ready sites, or optimize transport networks.
