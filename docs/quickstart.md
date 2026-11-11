# Query Guide

This guide queries the unified GeoPackage directly with GeoPandas or standard
SQLite. It does not create a second database or a pre-aggregated capacity
artifact.

## 1. Find and inspect the package

Run examples from the repository root after installing the package with
`python -m pip install -e .`. If the unified GeoPackage does not exist yet,
run `canco2-build` for the complete workflow, or `canco2-build-unified` when
all four Silver packages and the Statistics Canada Bronze boundaries already
exist. See the [workflow guide](workflow.md) for selective builds and reruns.

Use the most recent file under `data/processed/unified_storage/`:

```python
from pathlib import Path
import geopandas as gpd

package = sorted(
    Path("data/processed/unified_storage").glob(
        "*_13_CanadaGeologicalStorageUnified_AV_v2.gpkg"
    )
)[-1]

print(gpd.list_layers(package).to_string(index=False))
```

The four canonical tables are:

| Table | Grain | Geometry |
| --- | --- | --- |
| `storage_units` | One logical geological storage unit | No |
| `storage_features` | One spatial representation of a unit | Yes |
| `storage_assessments` | One assessment record | No |
| `administrative_features` | One agreement or tenure feature | Yes |

Read them as follows:

```python
units = gpd.read_file(package, layer="storage_units", ignore_geometry=True)
features = gpd.read_file(package, layer="storage_features")
assessments = gpd.read_file(
    package, layer="storage_assessments", ignore_geometry=True
)
tenure = gpd.read_file(package, layer="administrative_features")
```

## 2. Inventory sources and layers

Start with counts before filtering:

```python
print(units.groupby("source_dataset").size().rename("logical_units"))

print(
    features.groupby(
        ["source_dataset", "source_layer", "representation"],
        dropna=False,
    )
    .size()
    .rename("features")
)

print(
    assessments.groupby(
        ["source_dataset", "source_layer", "assessment_scope"],
        dropna=False,
    )
    .size()
    .rename("assessments")
)
```

Use exact values from these columns when filtering; they are the provenance
keys for the canonical rows.

## 3. Join assessments at the correct grain

An assessment declares whether it applies to one spatial feature or one logical
unit. Split first, then validate each join:

```python
feature_assessments = assessments.loc[
    assessments["assessment_scope"].eq("feature")
].merge(
    features[
        ["storage_feature_id", "storage_unit_id", "representation"]
    ],
    on=["storage_feature_id", "storage_unit_id"],
    how="left",
    validate="one_to_one",
)

unit_assessments = assessments.loc[
    assessments["assessment_scope"].eq("unit")
].merge(
    units[
        ["storage_unit_id", "storage_name", "data_class", "capacity_data"]
    ],
    on="storage_unit_id",
    how="left",
    validate="one_to_one",
)
```

Do not join unit-scoped assessments to every feature before summing. A logical
unit can have multiple spatial representations, which would duplicate its
assessment.

## 4. Query one source or storage type

NATCARB saline, coal, and oil/gas representations:

```python
natcarb = features.loc[features["source_dataset"].eq("NATCARB")]

saline = natcarb.loc[
    natcarb["source_layer"].eq("saline_resource_cells")
]
coal = natcarb.loc[
    natcarb["source_layer"].eq("coal_resource_cells")
]
oil_gas = natcarb.loc[
    natcarb["source_layer"].eq("oil_gas_resources")
]
```

The saline and coal layers contain whole grid cells whose source geometry
intersects Canada. The cells are not clipped to the national boundary, and
their capacity values are not prorated by overlap area. Oil/gas polygons are
selected using source-reported Canadian province or territory codes. The
saline and coal area representations remain in the NATCARB daughter package;
they are not interchangeable with the unified grid-cell representations.

Do not combine the grid and area representations or aggregate across provider
overlap and duplicate flags without an explicit source-specific rule.

BC aquifers with their unit-scoped assessments:

```python
bc_aquifers = unit_assessments.loc[
    unit_assessments["source_dataset"].eq("BC_STORAGE_ATLAS")
    & unit_assessments["source_layer"].eq("aquifer_units")
]
```

Atlantic qualitative prospectivity:

```python
atlantic_cos = feature_assessments.loc[
    feature_assessments["source_dataset"].eq("ATLANTIC_COS")
    & feature_assessments["assessment_type"].eq(
        "qualitative_chance_of_success"
    )
]
```

AER agreement-level polygons, excluding the retained tract parts:

```python
aer_agreements = tenure.loc[
    tenure["source_layer"].eq("aer_agreements")
]
```

## 5. Filter spatially

Every spatial layer is in EPSG:3978. Attribute filters are cheapest when the
canonical province/territory field is sufficient:

```python
alberta_features = features.loc[
    features["province_territory"].eq("Alberta")
]
```

For an arbitrary area of interest, project it to EPSG:3978 and use a spatial
join:

```python
area_of_interest = gpd.read_file("path/to/area_of_interest.gpkg").to_crs(3978)

selected = gpd.sjoin(
    features,
    area_of_interest[["geometry"]],
    how="inner",
    predicate="intersects",
).drop(columns="index_right")
```

`intersects` selects any touching feature; it does not apportion a source
capacity value by overlap area.

## 6. Summarize source-reported capacity

Classification lives on the logical unit, so join assessments to units before
selecting quantitative records:

```python
classified = assessments.merge(
    units[["storage_unit_id", "data_class", "capacity_data"]],
    on="storage_unit_id",
    how="left",
    validate="many_to_one",
)

capacity = classified.loc[
    classified["data_class"].eq("geological_storage_capacity")
    & classified["capacity_data"].fillna(False).astype(bool)
    & classified["storage_p50_tonnes"].notna()
]

source_summary = (
    capacity.groupby(
        ["source_dataset", "source_layer", "assessment_scope"],
        dropna=False,
    )
    .agg(
        assessment_count=("storage_assessment_id", "size"),
        source_reported_p50_tonnes=("storage_p50_tonnes", "sum"),
    )
    .reset_index()
)
```

Keep the groups separate. This output is a source-level screening summary, not
a deduplicated national capacity estimate. NATCARB cells can carry provider
overlap or duplicate semantics, and spatial overlap across sources is not a
cross-source identity rule. Null capacity is missing information, not zero.

## 7. Query with SQLite

A GeoPackage is a SQLite database. Standard library `sqlite3` can query
attributes and joins without loading geometry support:

```python
import sqlite3
import pandas as pd

sql = """
SELECT
    a.source_dataset,
    a.source_layer,
    a.assessment_scope,
    COUNT(*) AS assessment_count,
    SUM(a.storage_p50_tonnes) AS source_reported_p50_tonnes
FROM storage_assessments AS a
JOIN storage_units AS u
  ON u.storage_unit_id = a.storage_unit_id
WHERE u.data_class = 'geological_storage_capacity'
  AND u.capacity_data = 1
  AND a.storage_p50_tonnes IS NOT NULL
GROUP BY a.source_dataset, a.source_layer, a.assessment_scope
ORDER BY a.source_dataset, a.source_layer;
"""

with sqlite3.connect(package) as connection:
    summary = pd.read_sql_query(sql, connection)

print(summary)
```

SQLite can return the GeoPackage geometry blob, but it cannot evaluate spatial
predicates without a compatible spatial extension. Use GeoPandas for the
portable spatial workflow shown above.

Inspect metadata and validation results with SQL:

```python
metadata_sql = """
SELECT key, value
FROM metadata_canada_geological_storage_unified
ORDER BY key;
"""

qa_sql = """
SELECT check, value, notes
FROM qa_canada_geological_storage_unified
ORDER BY check;
"""

with sqlite3.connect(package) as connection:
    metadata = pd.read_sql_query(metadata_sql, connection)
    qa = pd.read_sql_query(qa_sql, connection)
```

## 8. Export a filtered result

Keep derived data outside the authoritative package:

```python
saline.to_file(
    "outputs/natcarb_saline_subset.gpkg",
    layer="saline_resource_cells",
    driver="GPKG",
)
```

Record the source package filename and your filter logic with any derived
output so the result can be reproduced.

## Run the complete example

```bash
python examples/unified_quickstart.py
```

The example validates expected tables and joins, prints source/layer summaries,
and does not modify the GeoPackage. See the [visual data catalog](data-catalog.md)
for source decomposition and [schema contract](schema.md) for field meanings.
