# CanCO2Re Geological Storage Data Pipeline

This repository contains the batch-processing, harmonization, validation, and schema-building code used to integrate heterogeneous geological CO2 storage datasets into a common CanCO2Re storage database.

The repository is intended to support a reusable, model-independent geological storage data product that can be consumed by downstream tools such as GIS workflows, network models, and energy system optimization models.

## Purpose

Geological CO2 storage data are distributed across multiple government, commercial, academic, and research-derived sources. These datasets may differ in:

- spatial representation;
- geological resolution;
- naming conventions;
- storage capacity estimates;
- injectivity estimates;
- uncertainty representation;
- administrative status;
- source provenance;
- update frequency;
- licensing restrictions.

The purpose of this repository is to provide a reproducible workflow for converting those heterogeneous inputs into a standardized, queryable storage database while preserving source-specific meaning and provenance.

The initial development target is Alberta geological storage data, with additional sources such as NRCan, NATCARB, CDL, and future research-derived datasets expected to be integrated incrementally.

## Repository scope

This repository is responsible for:

- acquiring public geological storage datasets where appropriate;
- validating local raw datasets supplied by the user;
- harmonizing source-specific fields into a common schema;
- preserving source-native identifiers and metadata;
- standardizing spatial reference systems and geometry handling;
- documenting source-field interpretations and transformations;
- building a portable CanCO2Re geological storage database;
- validating database structure, provenance, and spatial integrity;
- supporting batch execution of multiple storage-data ingestion workflows.

This repository is not responsible for:

- selecting model-specific storage capacity assumptions;
- assigning scenario-specific P10, P50, or P90 cases;
- optimizing CO2 transport or storage networks;
- replacing detailed reservoir simulation or geological characterization.

Those operations belong to downstream consumer models or research workflows.

## Conceptual workflow

```text
Public and local source datasets
        |
        v
Source acquisition / validation
        |
        v
Source-specific harmonization
        |
        v
Standardized source observations
        |
        v
CanCO2Re geological storage database
        |
        +--> GIS analysis
        +--> Geospatial-CANOE
        +--> NCAF / routing workflows
        +--> storage characterization studies
        +--> future research-derived datasets
```

## Alberta bronze source

The first reproducible bronze source is the Government of Alberta Carbon Sequestration Agreements dataset distributed through the Alberta GeoView service.

- Source page: `https://gis.energy.gov.ab.ca/GeoView/CarbonSequestration`
- Direct archive: `https://gis.energy.gov.ab.ca/GeoviewData/CS_Agreements_Shape.zip`
- Current shapefile: `CS_Agreements.shp`
- Source CRS: EPSG:3400 (NAD83 / Alberta 10-TM)

The production pipeline will acquire the public archive directly rather than depend on manually distributed copies. Retrieval metadata and a file checksum should be retained so that future changes at the unversioned download URL can be detected and reproduced.

### Source lineage check

An exploratory comparison was performed between the current public Alberta dataset and an earlier Alberta carbon sequestration agreement shapefile supplied through NRCan.

The comparison indicates that the two files are different temporal snapshots of the same Alberta carbon sequestration agreement data lineage rather than identical copies:

- the current Alberta dataset contains 45 features and 43 unique agreement numbers;
- the NRCan-provided copy contains 34 features and 30 unique agreement numbers;
- 22 agreement numbers are shared between the two datasets;
- 21 agreements occur only in the current Alberta release and are associated with newer 2024-2026 agreement dates;
- 8 agreements occur only in the NRCan copy and correspond to older 2022 records;
- some shared agreements have changed tract structures;
- several attributes have been recoded or updated between releases;
- six shared agreements have materially revised agreement areas and polygon geometries;
- reported agreement-area changes closely track changes calculated from the polygon geometries.

The NRCan copy also contains downstream ArcGIS-derived fields not present in the current public Alberta source. It is therefore treated as a historical comparison dataset rather than a production dependency.

For the initial Alberta workflow, the public Alberta GeoView download is the authoritative reproducible bronze input.

## Development workflow

Exploratory notebooks are kept under `notebooks/` and are used to inspect source structure, compare releases, and develop harmonization rules. Reusable transformations discovered during exploration are moved into the `canco2_storage` package rather than remaining embedded in notebooks.

The initial Alberta source-comparison notebook is:

```text
notebooks/01_ab_source_comparison.ipynb
```

The intended development pattern is:

```text
source exploration
        |
        v
source interpretation
        |
        v
reusable acquisition / harmonization code
        |
        v
canonical database build
        |
        v
validation
```

## Data policy

The repository tracks code, configuration, documentation, metadata, and exploratory notebooks. Raw and processed source datasets are not intended to be committed to Git.

Public datasets may be acquired programmatically when stable download endpoints are available. Licensed, proprietary, restricted, or otherwise non-redistributable datasets must be obtained separately by authorized users and placed in the expected local input locations.

Source licensing and provenance remain independent of the software contained in this repository.
