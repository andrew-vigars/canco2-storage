# Canadian CO₂ Geological Storage Data Pipeline

`canco2-storage` is a Python package for acquiring, harmonizing, validating, documenting, and publishing heterogeneous Canadian geological CO₂ storage datasets as reproducible Silver-layer products.

The repository is being developed to support a source-unified national geological storage data foundation for downstream research workflows. The emphasis is on preserving source meaning, provenance, uncertainty, licensing constraints, and spatial integrity rather than forcing unlike datasets into a single interpretation.

## Purpose

Canadian geological CO₂ storage information is distributed across government sources. These datasets can differ substantially in:

- spatial representation and geological resolution;
- naming conventions and source identifiers;
- storage-capacity and injectivity information;
- geological prospectivity or Chance of Success measures;
- regulatory and tenure status;
- uncertainty representation;
- coordinate reference systems;
- update frequency and temporal coverage;
- licensing and attribution requirements.

This repository provides a reproducible workflow for converting those heterogeneous inputs into standardized, queryable Silver products while preserving the original Bronze sources and documenting the transformations between them.

## Repository scope

This repository is responsible for:

- acquiring public geological storage datasets where appropriate;
- validating retained Bronze files and expected source products;
- preserving provider directory structures and source-native files;
- harmonizing source-specific fields into explicit Silver schemas;
- preserving source identifiers, provenance, and source-specific meaning;
- repairing and validating spatial geometries without modifying Bronze data;
- standardizing Silver spatial products to Canada Atlas Lambert CRS, EPSG:3978;
- generating dataset-level metadata, QA outputs, schema inventories, and field dictionaries;
- producing portable GeoPackage-based Silver datasets;
- generating human-readable dataset README files;
- supporting future integration into a national geological storage database.

This repository is **not** responsible for:

- selecting model-specific storage-capacity assumptions;
- assigning scenario-specific P10, P50, or P90 cases;
- treating geological prospectivity as equivalent to storage capacity;
- inferring injectivity where it is not supplied by the source;
- optimizing CO₂ transport or storage networks;
- replacing detailed reservoir simulation.

Those operations belong to downstream consumer models or research workflows.

## Data architecture

The current workflow follows a Bronze → Silver pattern.

```text
Original provider datasets
        |
        v
Bronze acquisition
- official source files retained unchanged
- provider directory structure preserved
- archives validated and hashed where supported
- expected source products validated
        |
        v
Exploration and validation
- schema inspection
- source comparison
- field interpretation
- geometry QA
- source-specific consistency checks
        |
        v
Silver harmonization
- harmonized field names
- EPSG:3978 spatial outputs
- preserved source identifiers and provenance
- explicit dataset classification
- metadata and QA tables
- schema inventories and field dictionaries
- generated dataset README documentation
        |
        v
Future national storage database
```

## Current dataset workflows

Three independent end-to-end public-data workflows are currently implemented.
They share processing conventions but retain different feature grains and
source meanings. They are not blindly concatenated into one flat table.

### Geological Survey of Canada Open File 8996

**Dataset:** *Preliminary assessment of geological carbon-storage potential of Atlantic Canada*  
**Source:** Geological Survey of Canada Open File 8996, Carey et al. (2023)  
**DOI:** `10.4095/332145`

The workflow acquires and harmonizes 15 regional Chance of Success (COS) shapefiles covering Mesozoic–Cenozoic and Upper Paleozoic storage units.

The resulting Silver layer is classified as:

```text
assessment_type = qualitative_chance_of_success
data_class = geological_prospectivity
capacity_data = False
capacity_status = not_quantitatively_assessed
injectivity_status = not_quantitatively_assessed
```

COS attributes are preserved as geological prospectivity indicators and are not interpreted as quantified storage capacity or injectivity.

### Northeast BC Geological Carbon Capture and Storage Atlas

**Dataset:** Northeast BC Geological Carbon Capture and Storage Atlas  
**Source:** Geoscience BC Report 2023-04, prepared by Canadian Discovery Ltd.
**Source project:** <https://www.geosciencebc.com/projects/2022-001/>

The workflow reconciles Appendix C logical pool and aquifer records with the
published Appendix E spatial layers. It produces selected pool and aquifer
logical-unit tables together with their spatial feature layers.

The BC Atlas contains quantitative screening estimates for storage units. Pool
and aquifer records must be interpreted at the logical-unit level; repeated or
multipart spatial features are not additive capacity records.

Important aquifer estimate fields include:

```text
p10_effective_storage_mt
p50_effective_storage_mt
p90_effective_storage_mt
theoretical_storage_mt
```

The workflow also preserves source-native values and flags discrepancies or
zero-theoretical anomalies for QA review.

### Alberta Energy Regulator Carbon Sequestration Agreements

**Dataset:** Carbon Sequestration Agreements  
**Source:** Alberta Energy Regulator (AER)
**Source project:** <https://gis.energy.gov.ab.ca/Geoview/CarbonSequestration>

The workflow acquires and harmonizes regulatory / tenure polygons associated with Alberta carbon sequestration pore-space agreements. The Silver product preserves both the source agreement-tract structure and a dissolved agreement-level layer.

The resulting layers are classified as:

```text
assessment_type = carbon_sequestration_agreement
data_class = regulatory_tenure
capacity_data = False
```

These polygons represent regulatory / tenure information and must not be interpreted as geological storage capacity, injectivity, prospectivity, or project-ready storage resource.

## Package structure

The codebase uses a `src/` package layout:

```text
canco2-storage/
├── pyproject.toml
├── README.md
├── notebooks/
├── scripts/
│   ├── run_bronze.py
│   └── run_silver.py
├── docs/
└── src/
    └── canco2_storage/
        ├── acquisition/
        │   ├── common.py
        │   ├── aer_agreements.py
        │   ├── gbc_ne_atlas.py
        │   └── gsc_atlantic.py
        ├── harmonize/
        │   ├── common.py
        │   ├── aer_agreements.py
        │   ├── gbc_ne_atlas.py
        │   └── gsc_atlantic.py
        ├── metadata/
        │   ├── common.py
        │   ├── aer_agreements.py
        │   ├── gbc_ne_atlas.py
        │   └── gsc_atlantic.py
        ├── orchestration/
        │   ├── bronze.py
        │   └── silver.py
        ├── execution/
        ├── schema/
        ├── validation/
        └── paths.py
```

The main responsibilities are separated as follows:

- `acquisition/` handles downloads, archive extraction, checksums, and Bronze validation;
- `harmonize/` performs source-specific schema transformation, geometry processing, QA, and Silver export; shared mechanics are in `harmonize/common.py`;
- `metadata/` contains shared CanCO₂Re submission helpers and dataset-specific README generation;
- `orchestration/` registers and runs the independent Bronze and Silver workflows;
- `paths.py` provides package-aware repository-root discovery;
- `notebooks/` contains exploratory analyses used to understand source datasets and inform production harmonizers.

The `schema/`, `validation/`, and `execution/` packages are reserved for continued consolidation of shared national-schema, validation, and orchestration logic.

## Installation

Python 3.12 or newer is required.

From the repository root, install the package and its runtime dependencies in editable mode:

```bash
python -m pip install -e .
```

The package currently declares the following core dependencies through `pyproject.toml`:

- `requests`
- `pandas`
- `geopandas`
- `shapely`

A successful editable installation should make the package importable without modifying `PYTHONPATH`:

```bash
python -c "import canco2_storage"
```

## Running the workflows

The current source-specific modules can be run directly with Python's module interface.

### 1. Acquire Bronze data

Run all registered acquisition workflows:

```bash
python scripts/run_bronze.py
```

Run one or more datasets selectively:

```bash
python scripts/run_bronze.py --dataset aer_agreements
python scripts/run_bronze.py --dataset gbc_ne_atlas --dataset gsc_atlantic
```

The registered acquisition dataset IDs are `aer_agreements`, `gbc_ne_atlas`,
and `gsc_atlantic`.

The underlying modules can also be run directly.

GSC Atlantic Open File 8996:

```bash
python -m canco2_storage.acquisition.gsc_atlantic
```

AER Carbon Sequestration Agreements:

```bash
python -m canco2_storage.acquisition.aer_agreements
```

Northeast BC Storage Atlas:

```bash
python -m canco2_storage.acquisition.gbc_ne_atlas
```

Use `--overwrite` to redownload and re-extract a source dataset:

```bash
python -m canco2_storage.acquisition.gsc_atlantic --overwrite
python -m canco2_storage.acquisition.aer_agreements --overwrite
python -m canco2_storage.acquisition.gbc_ne_atlas --overwrite
```

Both acquisition modules also accept `--raw-dir` for an alternate Bronze output directory.

### 2. Inspect source schemas without building Silver outputs

```bash
python -m canco2_storage.harmonize.gsc_atlantic --inspect-only
python -m canco2_storage.harmonize.aer_agreements --inspect-only
python -m canco2_storage.harmonize.gbc_ne_atlas --inspect-only
```

### 3. Build Silver outputs

Run all registered Silver workflows, including BC README generation:

```bash
python scripts/run_silver.py
```

Build selected independent packages:

```bash
python scripts/run_silver.py --dataset aer_agreements
python scripts/run_silver.py --dataset gbc_ne_atlas --dataset gsc_atlantic
```

The registered Silver dataset IDs are `aer_agreements`, `gbc_ne_atlas`, and
`gsc_atlantic`.

The underlying harmonizers can also be run directly.

```bash
python -m canco2_storage.harmonize.gsc_atlantic
python -m canco2_storage.harmonize.aer_agreements
python -m canco2_storage.harmonize.gbc_ne_atlas
```

The harmonizers validate the persisted artifacts after writing them rather than assuming the in-memory GeoDataFrames and serialized GeoPackages are identical.

## Output conventions

Processed outputs are written under:

```text
data/processed/<dataset_id>/
```

Submission filenames are generated from shared metadata using the pattern:

```text
YYYYMMDD_ActivityCode_DataType_CreatorInitials
```

The shared naming and documentation helpers are implemented in:

```text
src/canco2_storage/metadata/common.py
```

Current Silver products include dataset-specific combinations of:

- GeoPackage spatial layers;
- embedded metadata and QA tables;
- source-schema inventory CSV files;
- field-dictionary CSV files where applicable;
- generated Markdown README documentation.

### GSC Atlantic Silver product

The GSC workflow produces one `storage_units` feature layer containing the harmonized 15 source datasets, together with source metadata, QA, schema inventory, and generated README outputs.

### Northeast BC Silver product

The BC workflow produces one GeoPackage containing:

- `pool_features` — spatial representations of selected pool units;
- `pool_units` — one logical record per selected pool;
- `aquifer_features` — spatial representations of aquifer units;
- `aquifer_units` — one logical record per aquifer with standardized storage estimates;
- `metadata_gbc_ne_atlas` and `qa_gbc_ne_atlas` — embedded metadata and QA tables.

It also generates source-schema, source-metadata, QA-summary, and combined
field-dictionary sidecars. Inspection diagnostics are written under the
dataset's `inspection/` directory when requested.

### AER Silver product

The AER workflow produces one GeoPackage containing:

- `aer_agreement_tracts` — one feature per source agreement tract;
- `aer_agreements` — one feature per unique agreement after validated tract dissolve;
- `metadata_aer_agreements` — dataset-level provenance, interpretation, and classification metadata;
- `qa_aer_agreements` — dataset-level quality-assurance results.

Separate tract and agreement field dictionaries are also generated.

## Spatial standard

Silver spatial products use:

```text
EPSG:3978 — NAD83 / Canada Atlas Lambert
```

Source CRSs are retained in provenance fields and source geometries are repaired when necessary before and after reprojection. Bronze source files are never modified in place.

## Combining the Silver products

The three products are currently independent GeoPackages. They share common
processing conventions, provenance fields, geometry validation, and EPSG:3978,
but they represent different feature grains:

- AER agreements and agreement tracts are regulatory-tenure features;
- BC pools and aquifers are logical storage units with spatial representations
        and, for some units, P10/P50/P90 screening estimates;
- GSC Atlantic features are qualitative COS prospectivity polygons.

Any future national consolidation should preserve these distinctions. A
canonical sparse feature layer or query view may expose shared fields, while
capacity estimates, COS assessments, and tenure attributes should remain
semantically distinct and nullable where a source does not provide them.

## Data classification philosophy

A central design goal is to preserve the distinction between different kinds of storage-related information.

For example:

- `geological_prospectivity` describes qualitative or probabilistic geological suitability;
- `regulatory_tenure` describes administrative or pore-space agreement boundaries;
- future capacity-bearing datasets will be represented separately when explicit quantitative storage-resource estimates are available.

This avoids collapsing prospectivity, tenure, storage capacity, injectivity, and project feasibility into a single ambiguous "storage" layer.

## Validation principles

Production harmonizers are designed to fail explicitly when expected source structure changes or when critical assumptions are violated. Current checks include, where applicable:

- expected source files and shapefile sidecars;
- expected source CRS;
- required source fields;
- non-empty source layers;
- unique source identifiers;
- parseable date and numeric fields;
- geometry validity before and after reprojection;
- persisted GeoPackage feature counts and identifiers;
- final CRS validation;
- registered GeoPackage metadata / QA tables;
- preservation of provider warnings for QA review.

Provider-specific warnings can therefore be retained as provenance even when the resulting Silver geometry is valid.

## Development status

The package is currently versioned as `0.1.0` and should be considered an active research codebase rather than a finished national storage atlas.

The immediate architecture separates source acquisition, harmonization, and metadata generation so that additional provincial, federal, academic, or licensed datasets can be added without rewriting the full pipeline.

Future development is expected to focus on:

- formalizing shared national storage schemas;
- adding additional geological storage datasets;
- distinguishing capacity, injectivity, prospectivity, tenure, and uncertainty representations;
- improving common validation and orchestration utilities;
- linking spatially overlapping representations of the same geological storage system without discarding source provenance;
- producing source-unified national Silver products suitable for downstream model ingestion.

## Research use

This repository is intended to provide reusable data-engineering infrastructure rather than a single model-specific storage database. Downstream models should make their own explicit decisions about storage-resource scenarios, uncertainty treatment, admissible storage sites, capacity constraints, and network optimization.
