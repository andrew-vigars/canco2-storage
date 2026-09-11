# Canadian CO2 Geological Storage Data Pipeline

This repository contains the exploration, harmonization, validation, metadata,
and schema-building workflows used to integrate heterogeneous geological CO₂
storage datasets into a common set of source-unified storage databases.

The goal is to produce a reusable, model-independent geological storage data
products that can be used for downstream GIS analysis, network modelling, routing workflows,
and energy system optimization while preserving source-specific meaning,
uncertainty, provenance, and licensing constraints.

## Purpose

Geological CO₂ storage data are distributed across government, commercial,
academic, and research-derived sources. These datasets may differ in:

- spatial representation;
- geological resolution;
- naming conventions;
- storage-capacity estimates;
- injectivity estimates;
- uncertainty representation;
- administrative or tenure status;
- source provenance;
- coordinate reference systems;
- update frequency;
- licensing restrictions.

The purpose of this repository is to provide a reproducible workflow for
converting those heterogeneous inputs into standardized, queryable Silver
datasets while preserving the original Bronze sources and documenting the
transformations between them.

## Repository scope

This repository is responsible for:

- acquiring public geological storage datasets where appropriate;
- validating local raw datasets supplied by users;
- comparing alternative versions or temporal snapshots of source datasets;
- harmonizing source-specific fields into common schemas;
- preserving source-native identifiers, provenance, and metadata;
- standardizing spatial reference systems and geometry handling;
- documenting source-field interpretations and transformations;
- building portable GeoPackage-based Silver products;
- validating database structure, metadata, provenance, and spatial integrity;
- supporting future integration into a national CanCO2Re geological storage database.

This repository is not responsible for:

- selecting model-specific storage-capacity assumptions;
- assigning scenario-specific P10, P50, or P90 cases;
- optimizing CO₂ transport or storage networks;
- replacing detailed reservoir simulation;
- treating geological prospectivity as equivalent to storage capacity.

Those operations belong to downstream consumer models or research workflows.

## Data architecture

The current workflow follows a Bronze → Silver pattern.

```text
Original source datasets
        |
        v
Bronze
- source files preserved unchanged
- source CRS retained
- source identifiers retained
- source-specific schemas preserved
        |
        v
Exploration and validation
- schema inspection
- source comparison
- geometry QA
- field interpretation
- source linkage
- arithmetic / consistency checks
        |
        v
Silver
- harmonized field names
- standardized CRS
- preserved source provenance
- formal metadata
- QA tables
- queryable GeoPackage outputs
        |
        v
Future national storage database
        |
        +--> GIS analysis
        +--> Geospatial-CANOE
        +--> NCAF / routing workflows
        +--> storage characterization
        +--> scenario and uncertainty analysis
