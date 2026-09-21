# Canadian CO₂ Geological Storage Data Pipeline

`canco2-storage` is a Python package for acquiring, harmonizing, validating, documenting, and publishing heterogeneous geological CO₂ storage datasets as reproducible Silver-layer products and a unified Canadian storage atlas.

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

This repository provides a reproducible workflow for converting those heterogeneous inputs into standardized, queryable Silver products and a canonical unified GeoPackage while preserving the original Bronze sources and documenting the transformations between them.

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
- combining the completed Silver packages into a unified Canadian geological storage GeoPackage;
- retaining source lineage, metadata, and QA in the unified product.

This repository is **not** responsible for:

- selecting model-specific storage-capacity assumptions;
- assigning scenario-specific P10, P50, or P90 cases;
- treating geological prospectivity as equivalent to storage capacity;
- inferring injectivity where it is not supplied by the source;
- optimizing CO₂ transport or storage networks;
- replacing detailed reservoir simulation.

Those operations belong to downstream consumer models or research workflows.

## Data architecture

The current workflow follows Bronze acquisition → source-specific Silver
packages → a unified atlas. See the [workflow guide and Mermaid diagram](docs/workflow.md)
for commands, dependencies, validation, and reruns.

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
Unified Canadian geological storage atlas
- canonical storage-unit, feature, and assessment tables
- administrative tenure features kept separate
- source lineage, metadata, and QA retained
```

## Current dataset workflows

Four independent end-to-end public-data workflows are implemented.
They share processing conventions but retain different feature grains and
source meanings. They are not blindly concatenated into one flat table.

### Geological Survey of Canada Open File 8996

**Dataset:** *Preliminary assessment of geological carbon-storage potential of Atlantic Canada*  
**Source:** Geological Survey of Canada Open File 8996, Carey et al. (2023)  
**Source project:** <https://publications.gc.ca/site/eng/9.927009/publication.html>
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

### DOE/NETL NATCARB All Data v1502

**Dataset:** NATCARB All Data v1502 geological storage resources
**Source:** U.S. Department of Energy, National Energy Technology Laboratory
**Source resource:** <https://edx.netl.doe.gov/dataset/natcarb-alldata-v1502>

The workflow harmonizes five NATCARB spatial representations: saline-resource
and coal-resource 10 km grid cells, saline-resource and coal-resource extent
polygons, and oil/gas storage-resource polygons. It also retains the ten
provider domain tables required to interpret coded attributes.

Grid-cell and polygon representations remain separate source products. Provider
duplicate and overlap flags are preserved and must be considered before any
aggregation. NATCARB storage-resource estimates are regional screening values,
not demonstrated injectivity, permitted injection capacity, or project-ready
capacity.

### Unified Canadian geological storage atlas

The completed unified build consumes the four dated Silver GeoPackages and
produces a canonical GeoPackage under `data/processed/unified_storage/`.
NATCARB saline and coal grid cells are subset to Canadian provinces and
territories using the Statistics Canada digital boundaries acquired by the
Bronze workflow.

The unified GeoPackage contains four canonical tables:

```text
storage_units             logical geological storage units
storage_features          spatial representations of storage units
storage_assessments       capacity, prospectivity, and related assessments
administrative_features   regulatory and tenure features
```

It also retains a normalized source catalog, precursor metadata and QA,
unified metadata, and unified QA tables. A companion README and dated schema,
metadata, QA-summary, and field-dictionary files are generated from the
persisted GeoPackage. The documentation tables are registered as standard
GeoPackage attribute tables in `gpkg_contents`, making them discoverable in
GeoPackage-aware GIS clients. No external registration with geopackage.org or
QGIS is required; a QGIS project is optional for saved styling and map layout.

Researchers can begin with the [GeoPackage researcher quickstart](docs/quickstart.md)
or run the matching executable example:

```bash
python examples/unified_quickstart.py
```

The quickstart uses the GeoPackage directly and does not create a second SQL,
SQLite, or pre-aggregated capacity artifact.

## Package structure

The codebase uses a `src/` package layout:

```text
canco2-storage/
├── pyproject.toml
├── README.md
├── notebooks/
├── scripts/
│   ├── build_geopackages.py
│   ├── build_unified.py
│   ├── build_all.py
│   ├── run_bronze.py
│   └── run_silver.py
├── docs/
│   ├── quickstart.md
│   ├── schema.md
│   └── workflow.md
├── examples/
│   └── unified_quickstart.py
└── src/
    └── canco2_storage/
        ├── acquisition/
        │   ├── common.py
        │   ├── aer_agreements.py
        │   ├── gbc_ne_atlas.py
        │   ├── gsc_atlantic.py
        │   ├── natcarb_doe.py
        │   └── statcan_digital_boundaries.py
        ├── harmonize/
        │   ├── common.py
        │   ├── aer_agreements.py
        │   ├── gbc_ne_atlas.py
        │   ├── gsc_atlantic.py
        │   ├── natcarb_doe.py
        │   └── unified_atlas.py
        ├── metadata/
        │   ├── common.py
        │   ├── aer_agreements.py
        │   ├── gbc_ne_atlas.py
        │   ├── gsc_atlantic.py
        │   ├── natcarb_doe.py
        │   └── unified_atlas.py
        ├── orchestration/
        │   ├── bronze.py
        │   ├── build_all.py
        │   ├── geopackages.py
        │   ├── silver.py
        │   └── unified.py
        └── paths.py
```

The main responsibilities are separated as follows:

- `acquisition/` handles downloads, archive extraction, checksums, and Bronze validation;
- `harmonize/` performs source-specific schema transformation, geometry processing, QA, and Silver export; shared mechanics are in `harmonize/common.py`;
- `metadata/` contains shared CanCO₂Re submission helpers and dataset-specific README generation;
- `orchestration/` registers and runs the independent Bronze and Silver workflows;
- `paths.py` provides package-aware repository-root discovery;
- `notebooks/` contains exploratory analyses used to understand source datasets and inform production harmonizers. The production unified build is implemented in `harmonize/unified_atlas.py` and orchestrated through `scripts/build_all.py`.

The stable layer and interpretation contract is documented in [docs/schema.md](docs/schema.md).

## Installation

Python 3.12 or newer is required.

From the repository root, install the package and its runtime dependencies in editable mode. Include the test extra when developing:

```bash
python -m pip install -e .
python -m pip install -e ".[test]"
```

The package currently declares the following core dependencies through `pyproject.toml`:

- `requests`
- `pandas`
- `geopandas`
- `shapely`
- `openpyxl`
- `pyproj`
- `pyogrio`

Installation also provides these console commands: `canco2-build`,
`canco2-build-geopackages`, `canco2-build-unified`, `canco2-run-bronze`, and
`canco2-run-silver`.

A successful editable installation should make the package importable without modifying `PYTHONPATH`:

```bash
python -c "import canco2_storage"
```

## Running the workflows

The complete workflow is the recommended entry point. Run it from the
repository root after installing the package:

```bash
python scripts/build_all.py
```

This acquires the registered Bronze inputs, builds the four independent Silver
GeoPackages, builds the unified atlas, and generates its companion README.
The equivalent installed command is:

```bash
canco2-build
```

Use `--skip-bronze` or `--skip-silver` when the corresponding inputs or
outputs already exist. Both options still run the unified stage; passing both
together is rejected. Use `--datasets` to limit precursor processing; the
unified build still requires all four Silver source packages and the Statistics
Canada boundaries. To rebuild only the unified product, use `canco2-build-unified`.

The individual workflow stages remain available for inspection and reruns.

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

The registered acquisition dataset IDs are `statcan_digital_boundaries`,
`aer_agreements`, `gbc_ne_atlas`, `gsc_atlantic`, and `natcarb_doe`. Statistics
Canada boundaries support the unified stage and do not produce a Silver package.

The installed Bronze and Silver commands use `--datasets` with a space-separated
list; the `run_bronze.py` and `run_silver.py` scripts use repeatable `--dataset`:

```bash
canco2-run-bronze --datasets statcan_digital_boundaries gsc_atlantic
canco2-run-silver --datasets gsc_atlantic natcarb_doe
```

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

DOE/NETL NATCARB All Data v1502:

```bash
python -m canco2_storage.acquisition.natcarb_doe
```

Use `--overwrite` to redownload and re-extract a source dataset:

```bash
python -m canco2_storage.acquisition.gsc_atlantic --overwrite
python -m canco2_storage.acquisition.aer_agreements --overwrite
python -m canco2_storage.acquisition.gbc_ne_atlas --overwrite
python -m canco2_storage.acquisition.natcarb_doe --overwrite
```

Acquisition modules also accept `--raw-dir` for an alternate Bronze output directory.

### 2. Inspect source schemas without building Silver outputs

```bash
python -m canco2_storage.harmonize.gsc_atlantic --inspect-only
python -m canco2_storage.harmonize.aer_agreements --inspect-only
python -m canco2_storage.harmonize.gbc_ne_atlas --inspect-only
```

### 3. Build Silver outputs

Run all registered Silver workflows, including dataset README generation:

```bash
python scripts/run_silver.py
```

Build selected independent packages:

```bash
python scripts/run_silver.py --dataset aer_agreements
python scripts/run_silver.py --dataset gbc_ne_atlas --dataset gsc_atlantic
```

The registered Silver dataset IDs are `aer_agreements`, `gbc_ne_atlas`,
`gsc_atlantic`, and `natcarb_doe`.

The underlying harmonizers can also be run directly.

```bash
python -m canco2_storage.harmonize.gsc_atlantic
python -m canco2_storage.harmonize.aer_agreements
python -m canco2_storage.harmonize.gbc_ne_atlas
python -m canco2_storage.harmonize.natcarb_doe
```

The harmonizers validate the persisted artifacts after writing them rather than assuming the in-memory GeoDataFrames and serialized GeoPackages are identical.

Direct BC, Atlantic, and NATCARB harmonizer calls require a subsequent call to
their matching `canco2_storage.metadata.<dataset_id>` module to generate the
README. The Silver orchestrator runs both steps; AER generates its README
inside its harmonizer.

### 4. Build Bronze and Silver GeoPackages together

The top-level builder runs the registered Bronze acquisition workflows followed
by the corresponding Silver workflows:

```bash
python scripts/build_geopackages.py
```

Build selected datasets, or rerun only one layer when Bronze inputs already
exist:

```bash
python scripts/build_geopackages.py --datasets natcarb_doe aer_agreements
python scripts/build_geopackages.py --skip-bronze
python scripts/build_geopackages.py --skip-silver
```

Build only the unified atlas from existing dated Silver GeoPackages:

```bash
python scripts/build_unified.py
```

Validate an existing unified GeoPackage without rebuilding it:

```bash
python scripts/build_unified.py --validate-existing path/to/unified.gpkg
```

## Output conventions

Processed outputs are written under:

```text
data/processed/<dataset_id>/
```

Submission filenames are generated from shared metadata using the pattern:

```text
YYYYMMDD_ActivityCode_DataType_CreatorInitials
```

The unified GeoPackage adds the build variant suffix `_v2.gpkg`. Rebuilding
on the same date replaces same-named products; a new date creates a new set.
Unified builds select the newest canonical filename independently for each
Silver source, so the selected source dates can differ.

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

### NATCARB Silver product

The GeoPackage contains `saline_resource_cells`, `saline_resource_areas`,
`coal_resource_cells`, `coal_resource_areas`, and `oil_gas_resources`, plus ten
provider domain tables, `metadata_natcarb_doe`, and `qa_natcarb_doe`. Schema,
metadata, QA, field-dictionary, and README sidecars accompany the package.
The Silver package retains the source coverage; Canadian selection happens
in the unified build.

## Spatial standard

Silver spatial products use:

```text
EPSG:3978 — NAD83 / Canada Atlas Lambert
```

Source CRSs are retained in provenance fields and source geometries are repaired when necessary before and after reprojection. Bronze source files are never modified in place.

## Unified atlas interpretation

The unified GeoPackage provides a common query surface without pretending that
all source records have the same meaning. It preserves the distinctions among:

- geological storage capacity and screening resource estimates;
- qualitative geological prospectivity and Chance of Success;
- regulatory and tenure evidence; and
- source-specific feature representations and logical storage units.

Source identifiers remain valid within their documented source dataset and
layer. The unified product does not infer injectivity, deduplicate overlapping
resources, convert prospectivity into capacity, or treat tenure polygons as
geological storage objects.

## Data classification philosophy

A central design goal is to preserve the distinction between different kinds of storage-related information.

For example:

- `geological_prospectivity` describes qualitative or probabilistic geological suitability;
- `regulatory_tenure` describes administrative or pore-space agreement boundaries;
- `geological_storage_capacity` describes quantitative source-reported estimates from the BC atlas and capacity-bearing NATCARB layers.

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

The repository is at the `0.2.0a1` core-alpha milestone. The complete
Bronze-to-Silver-to-unified workflow is implemented, including persisted
metadata, QA, source lineage, and generated documentation. The products are
ready for research use and review; they are not a claim that the underlying
source estimates are project-ready storage capacity or demonstrated
injectivity.

Future work can add source datasets, improve cross-source identity and
validation, and define downstream optimizer policies without changing the
source-faithful products delivered by this core workflow.

## Research use

This repository is intended to provide reusable data-engineering infrastructure rather than a single model-specific storage database. Downstream models should make their own explicit decisions about storage-resource scenarios, uncertainty treatment, admissible storage sites, capacity constraints, and network optimization.
