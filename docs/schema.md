# CANCO2-Storage Silver Schema

**Schema contract:** `1.0.0`  
**Status:** implemented Silver interface  
**Scope:** dated GeoPackage artifacts produced by the harmonizers

This document defines the implemented Silver GeoPackage contract. The
sidecar field dictionaries and source-schema inventories are the authoritative
field-level references for each dated output. This page records the stable
concepts and layer grain that users need when querying multiple products.

## Contract and compatibility

The schema version applies to the semantic interface below, not to a source
provider's publication version or to a dated submission filename. A patch
release may clarify descriptions without changing field meaning, layer grain,
or identifier behavior. A minor release may add nullable fields or new
registered layers. A major release is required for renaming fields, changing
units, changing record grain, changing identifier meaning, or changing the
interpretation of an existing classification value.

Every Silver package must retain its source dataset identity, source
identifiers, source CRS where spatial input exists, and the dataset-specific
metadata and QA tables documented below. A field dictionary shipped with a
package remains the authoritative type and field inventory for that dated
artifact; this document is the stable cross-package contract.

## Common conventions

### Spatial reference and geometry

All Silver feature layers use EPSG:3978, NAD83 / Canada Atlas Lambert. The
harmonizers retain the source CRS in provenance fields where the layer has a
source geometry. They calculate the following measures after reprojection:

| Field | Meaning | Units |
| --- | --- | --- |
| `geometry_area_m2` | Area of the Silver geometry | square metres |
| `geometry_area_ha` | `geometry_area_m2 / 10000` | hectares |
| `geometry_perimeter_m` | Perimeter of the Silver geometry | metres |

Invalid non-null geometries are repaired on a copy of the source data. Bronze
files are never edited. Null or empty geometries are not accepted in persisted
Silver feature layers.

### Classification fields

Where present, these fields describe the meaning of the record rather than a
universal storage-resource estimate:

| Field | Meaning |
| --- | --- |
| `assessment_type` | The source assessment or product type |
| `data_class` | Repository classification such as `geological_prospectivity`, `geological_storage_capacity`, or `regulatory_tenure` |
| `capacity_data` | Whether the record carries quantitative source capacity or storage-resource estimates |
| `source_dataset` | Source dataset identity |
| `source_crs` | CRS of the source geometry, when applicable |

These fields do not make unlike datasets interchangeable. In particular,
Chance of Success is not capacity, an agreement boundary is not a storage
resource, and a storage-resource estimate is not demonstrated injectivity.

### Semantic roles

The following roles are intentionally orthogonal:

| Role | Contract meaning | Current datasets |
| --- | --- | --- |
| `geological_storage_capacity` | Quantitative source-reported storage-resource estimates, with units and source method preserved | BC atlas, NATCARB capacity-bearing layers |
| `geological_prospectivity` | Geological screening or likelihood evidence; it is not a mass estimate | GSC Atlantic COS |
| `regulatory_tenure` | Rights, agreements, permits, or other regulatory spatial evidence | AER agreements |

`capacity_data = False` means that quantitative capacity must not be inferred
from the layer. Null capacity is absence of an estimate, not zero capacity.
`injectivity_status` is separate from both capacity and prospectivity and must
not be inferred from either one.

## Optimizer boundary

This Silver contract is descriptive; it does not silently encode an optimizer's
admissibility policy. An optimizer input specification must declare, for each
role, whether it is a hard gate, a soft score/penalty, or informational only.
Until that policy is versioned separately, the safe default is:

- capacity layers provide candidate resource estimates, not demonstrated
	deliverability;
- prospectivity layers provide evidence or ranking features, not capacity;
- tenure layers provide spatial/legal evidence, not geological suitability;
- no role may be converted to another role by filling absent values or by
	multiplying estimates across spatial representations.

The unified optimizer interface should therefore expose separate references
to capacity, prospectivity, and tenure inputs, along with the explicit policy
version used to combine them. A future optimizer schema may choose hard tenure
admissibility and soft geological scoring, for example, but that choice is not
part of Silver `1.0.0`.

## GeoPackage contract by dataset

### `aer_agreements`

One GeoPackage contains the following registered layers and tables:

| Name | Type | Grain |
| --- | --- | --- |
| `aer_agreement_tracts` | `features` | One source agreement tract |
| `aer_agreements` | `features` | One dissolved agreement ID |
| `metadata_aer_agreements` | `attributes` | Dataset-level provenance and classification |
| `qa_aer_agreements` | `attributes` | Dataset-level QA results |

The tract layer preserves `agreement_id`, `tract_id`, source agreement fields,
date fields, source feature identifiers, provenance, classification, and
geometry measures. The agreement layer preserves the agreement-level fields,
`tract_count`, and the dissolved geometry. `zone_description` can preserve
distinct tract-level descriptions during the dissolve.

The source identifiers are text values. This is intentional because values such
as tract IDs can contain leading zeroes.

### `gbc_ne_atlas`

One GeoPackage contains:

| Name | Type | Grain |
| --- | --- | --- |
| `pool_features` | `features` | A published spatial representation of a pool |
| `pool_units` | `attributes` | One logical pool storage unit |
| `aquifer_features` | `features` | A published spatial representation of an aquifer |
| `aquifer_units` | `attributes` | One logical aquifer storage unit |
| `metadata_gbc_ne_atlas` | `attributes` | Dataset-level provenance and classification |
| `qa_gbc_ne_atlas` | `attributes` | Dataset-level QA and reconciliation results |

Pool logical records use `storage_unit_id` and include source classification,
well and reservoir attributes, plus source-linked estimates where supplied.
Aquifer logical records use `storage_unit_id` and include:

- `p10_effective_storage_mt`, `p50_effective_storage_mt`, and
	`p90_effective_storage_mt`;
- `theoretical_storage_mt` and `theoretical_storage_method`;
- source-native estimate fields; and
- reconciliation and anomaly flags.

The logical-unit tables are the correct grain for capacity analysis. Multiple
features in a feature layer represent spatial parts or repeated source
representations and must not be summed as independent capacity records.

### `gsc_atlantic`

The GeoPackage contains:

| Name | Type | Grain |
| --- | --- | --- |
| `storage_units` | `features` | One feature from one of 15 mapped source layers |
| `metadata_gsc_atlantic` | `attributes` | Dataset-level provenance and classification |
| `qa_gsc_atlantic` | `attributes` | Dataset-level QA results |

The feature layer includes `feature_id`, `storage_unit_id`, geological unit
name and group, assessment area, COS components, `total_cos`, source feature
provenance, and the common classification fields. `trap_cos` is nullable for
source layers that provide only reservoir and seal components.

The dataset is classified as `qualitative_chance_of_success` and
`geological_prospectivity`, with `capacity_data = False`.

### `natcarb_doe`

The five spatial representations remain separate:

| Name | Representation | Capacity flag |
| --- | --- | --- |
| `saline_resource_cells` | Saline 10 km resource grid cells | true |
| `saline_resource_areas` | Saline resource extent polygons | false |
| `coal_resource_cells` | Coal 10 km resource grid cells | true |
| `coal_resource_areas` | Coal resource extent polygons | false |
| `oil_gas_resources` | Oil and gas storage-resource polygons | true |

The package also retains ten provider domain tables as non-spatial reference
tables, plus `metadata_natcarb_doe` and `qa_natcarb_doe`. The exact domain table
names are source-controlled and are included in the generated source schema
inventory and field dictionary.

Grid and polygon layers are different source representations, not parent-child
rows. Provider `ASSESSED`, `OVERLAP`, `DUPLICATE`, and P50-method semantics are
preserved. The harmonizer does not remove duplicates, aggregate overlaps, or
infer relationships between representations.

## Sidecar artifacts

Each dataset writes dated artifacts under `data/processed/<dataset_id>/` using
the pattern `YYYYMMDD_13_DataType_AV`. Depending on the workflow, these include:

- a Silver GeoPackage;
- a source-schema inventory;
- source metadata and QA-summary CSV files;
- one or more field dictionaries; and
- a generated Markdown README.

Inspection-only diagnostics, such as workbook inventories, layer inventories,
pool reconciliation, or capacity QA, are written under the dataset's
`inspection/` directory when supported. They are diagnostics and do not replace
the persisted GeoPackage contract.

## Required cross-dataset fields

The following fields are the shared query surface where a dataset supplies the
concept. Dataset-specific layers may add fields, but must not reuse these names
with different meanings or units:

| Field | Required meaning |
| --- | --- |
| `storage_unit_id` | Stable identifier for one logical storage object; never a spatial-part count |
| `storage_feature_id` or `feature_id` | Stable identifier for one spatial feature where the layer is feature-grained |
| `source_dataset` | Repository source dataset identity |
| `assessment_type` | Assessment or product type represented by the record |
| `data_class` | One of the documented semantic roles, where applicable |
| `capacity_data` | Boolean declaration that quantitative source capacity is present |
| `geometry` | Spatial geometry in EPSG:3978 for feature layers |

Logical-unit tables and spatial-feature tables are different grains. A spatial
feature count must never be used as a capacity multiplier unless a source
explicitly defines additive values at that grain.

## Querying guidance

Use the logical-unit tables for BC capacity summaries. Use `storage_units` for
GSC prospectivity analysis. Use AER agreement or tract layers for tenure
analysis. For NATCARB, select a representation explicitly and inspect provider
flags before aggregation. A national view should preserve these distinctions
and should not coerce absent capacity or injectivity values into zero.
