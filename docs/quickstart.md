# Researcher Quickstart

This guide uses the unified GeoPackage directly. It does not create a second
SQLite database, SQL export, or pre-aggregated capacity layer.

## Open the package

Run the examples from the repository root after installing the package with
`python -m pip install -e .`. If no unified GeoPackage exists yet, run
`canco2-build` for the complete workflow, or `canco2-build-unified` when all four
Silver packages and the Statistics Canada Bronze boundaries already exist.
See the [workflow guide](workflow.md) for selective builds and reruns.

Use the most recent file under `data/processed/unified_storage/`:

```python
from pathlib import Path
import geopandas as gpd

package = sorted(
    Path("data/processed/unified_storage").glob(
        "*_13_CanadaGeologicalStorageUnified_AV_v2.gpkg"
    )
)[-1]

units = gpd.read_file(package, layer="storage_units", ignore_geometry=True)
features = gpd.read_file(package, layer="storage_features")
assessments = gpd.read_file(
    package,
    layer="storage_assessments",
    ignore_geometry=True,
)
tenure = gpd.read_file(package, layer="administrative_features")
```

The GeoPackage can also be opened directly in QGIS or ArcGIS Pro. All spatial
layers use EPSG:3978, NAD83 / Canada Atlas Lambert.

## Choose the table by grain

| Table | Grain | Use |
| --- | --- | --- |
| `storage_units` | One logical geological storage unit | Unit identity and source classification |
| `storage_features` | One spatial representation | Mapping and spatial selection |
| `storage_assessments` | One capacity, prospectivity, or related assessment | Quantitative or qualitative assessment values |
| `administrative_features` | One regulatory or tenure feature | AER agreement and tract mapping |

The central rule is: **a spatial feature is not automatically a capacity record**.
A logical unit can have multiple spatial features, and one assessment can apply
to a unit rather than to each feature.

## Join assessments safely

Use the assessment scope to choose the join key:

```python
feature_assessments = assessments.loc[
    assessments["assessment_scope"].eq("feature")
].merge(
    features[["storage_feature_id", "storage_unit_id", "source_layer"]],
    on="storage_feature_id",
    how="left",
    validate="many_to_one",
)

unit_assessments = assessments.loc[
    assessments["assessment_scope"].eq("unit")
].merge(
    units[
        [
            "storage_unit_id",
            "storage_name",
            "data_class",
            "capacity_data",
        ]
    ],
    on="storage_unit_id",
    how="left",
    validate="many_to_one",
)
```

Use `storage_feature_id` for feature-scoped assessments and
`storage_unit_id` for unit-scoped assessments. Do not join unit-scoped
assessments to every feature before summing capacity; that duplicates values for
multi-feature units.

## Summarize capacity

For a first screening summary, aggregate only unit-scoped, quantitative
capacity assessments:

```python
capacity = unit_assessments.loc[
    unit_assessments["data_class"].eq("geological_storage_capacity")
    & unit_assessments["capacity_data"].fillna(False).astype(bool)
    & unit_assessments["storage_p50_tonnes"].notna()
]

summary = (
    capacity.groupby(["source_dataset", "source_layer"], dropna=False)
    .agg(
        assessment_count=("storage_assessment_id", "size"),
        p50_tonnes=("storage_p50_tonnes", "sum"),
    )
    .reset_index()
)
print(summary)
```

This is a source-level screening summary, not a deduplicated national storage
capacity estimate. Preserve `source_dataset`, `source_layer`, `capacity_method`,
and source-specific QA flags when interpreting or aggregating results. Null
capacity means that the source did not provide an estimate; it is not zero.

## Filter NATCARB representations

The unified product preserves representation and source-layer distinctions:

```python
natcarb = features.loc[features["source_dataset"].eq("NATCARB")]

natcarb_grid_cells = natcarb.loc[
    natcarb["source_layer"].isin(
        ["saline_resource_cells", "coal_resource_cells"]
    )
]

natcarb_oil_gas = natcarb.loc[
    natcarb["source_layer"].eq("oil_gas_resources")
]
```

The unified package contains the Canadian NATCARB saline and coal grid-cell
subset plus Canadian oil-and-gas resource polygons. The saline and coal area
representations remain in the NATCARB Silver package and are not interchangeable
with grid cells.

The grid-cell subset includes whole cells intersecting Canada's boundary; cells
are not clipped and capacity is not prorated by overlap area. Oil/gas polygons
are selected using source-reported Canadian province/territory codes.

Do not merge grid cells and polygons, count a spatial representation as a
separate storage unit, or aggregate across provider overlap/duplicate flags
without an explicit source-specific rule.

## Keep semantic roles separate

Use the classification fields before combining records:

```python
print(
    assessments.merge(
        units[["storage_unit_id", "data_class", "capacity_data"]],
        on="storage_unit_id",
        how="left",
        validate="many_to_one",
    ).groupby(
        ["data_class", "assessment_type", "capacity_data"],
        dropna=False,
    ).size()
)
```

Interpret the roles as follows:

- `geological_storage_capacity`: quantitative source-reported storage-resource estimates;
- `geological_prospectivity`: geological screening evidence such as Atlantic COS, not tonnes;
- `regulatory_tenure`: agreement or rights evidence, not geological capacity.

For mapping, keep these outputs separate:

```python
capacity_features = features.loc[
    features["data_class"].eq("geological_storage_capacity")
]
prospectivity_features = features.loc[
    features["data_class"].eq("geological_prospectivity")
]
tenure_features = tenure
```

## Provenance and QA

The GeoPackage exposes these registered attribute tables through `gpkg_contents`:

- `source_catalog_canada_geological_storage_unified`
- `source_metadata_canada_geological_storage_unified`
- `source_qa_canada_geological_storage_unified`
- `metadata_canada_geological_storage_unified`
- `qa_canada_geological_storage_unified`

The companion CSV files beside the GeoPackage are convenient for spreadsheet
inspection, but the GeoPackage tables are the authoritative package contents.

## Run the example

From the repository root:

```bash
python examples/unified_quickstart.py
```

The example reads the GeoPackage, validates the expected tables and joins, and
prints capacity, NATCARB, semantic-role, and provenance summaries. It does not
write or modify the GeoPackage.

For the stable schema contract and source-specific limitations, see
[`docs/schema.md`](schema.md) and [`docs/workflow.md`](workflow.md).
