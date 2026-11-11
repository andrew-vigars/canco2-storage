# Beginner Quickstart

This guide starts with a downloaded copy of the repository and ends with the
Canadian geological storage atlas open in ArcGIS Pro or QGIS. No previous
Python experience is required.

The workflow downloads public source datasets and builds the GeoPackages on
your computer. Allow several hundred megabytes for downloads and a few
gigabytes of working disk space.

## 1. Download the repository

1. Open the [canco2-storage GitHub repository](https://github.com/andrew-vigars/canco2-storage).
2. Select **Code**, then **Download ZIP**.
3. In File Explorer, right-click the downloaded ZIP and select **Extract All**.
4. Move the extracted folder somewhere easy to find, such as Documents.

Do not run the workflow from inside the ZIP preview. Use the extracted folder
that contains **pyproject.toml**, **README.md**, and the **scripts** directory.

Git users can clone the repository instead:

    git clone https://github.com/andrew-vigars/canco2-storage.git
    cd canco2-storage

## 2. Install Python

The project requires **Python 3.12 or newer**. Download a current Windows
installer from [python.org](https://www.python.org/downloads/windows/) if an
appropriate version is not already installed.

During installation, enable **Add python.exe to PATH**. Close and reopen the
terminal after installing Python.

Open the extracted repository folder in File Explorer. Right-click an empty
area and choose **Open in Terminal**. On Windows 10, select the address bar,
type **powershell**, and press Enter.

Check the installed version:

    py --version

The result should report Python 3.12 or newer.

## 3. Create and activate a virtual environment

A virtual environment keeps this project's Python packages separate from other
software. Create it once from the repository folder:

    py -m venv .venv

Activate it in PowerShell:

    .venv\Scripts\Activate.ps1

The terminal prompt should now begin with **(.venv)**. If PowerShell blocks the
activation script, run:

    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .venv\Scripts\Activate.ps1

The policy change applies only to the current terminal window.

For Command Prompt instead of PowerShell:

    .venv\Scripts\activate.bat

For macOS or Linux:

    python3 -m venv .venv
    source .venv/bin/activate

## 4. Install the project

With **(.venv)** visible in the prompt, run:

    python -m pip install --upgrade pip
    python -m pip install -e .

The second command reads the existing **pyproject.toml** and installs the
project and its required packages. You do not need to create or initialize a
new pyproject file. The **-e** means the installation uses the code in this
folder.

Confirm that the project command is available:

    canco2-build --help

## 5. Build the GeoPackages

Run the complete Bronze → Silver → unified workflow:

    canco2-build

If the short command is not recognized, use:

    python scripts\build_all.py

Leave the terminal open until the command finishes. The workflow downloads
files from the source agencies, validates them, builds four daughter
GeoPackages, and then builds the unified Canadian atlas. A warning about a
polygon with more than 100 parts is expected.

The main output is written to:

    data\processed\unified_storage\

Its dated filename ends with:

    _13_CanadaGeologicalStorageUnified_AV_v2.gpkg

The daughter GeoPackages remain in their individual directories under
**data\processed**.

## 6. Understand the unified file

The GeoPackage contains two map layers and several related tables:

| Name | Type | Contents |
| --- | --- | --- |
| storage_features | Map layer | BC, Atlantic, and NATCARB storage geometries |
| administrative_features | Map layer | Alberta sequestration agreements and source tracts |
| storage_units | Table | Logical unit names, formations, and classifications |
| storage_assessments | Table | Capacity, geological properties, and Chance of Success |

Other metadata, provenance, and QA tables document how the atlas was built.

The important relationship is:

    storage_units (one) ─────< storage_features (one or more)
           │                          │
           └────< storage_assessments >──── unit- or feature-scoped

Do not assume every polygon has a separate capacity value. BC assessments are
attached to logical units, while Atlantic and NATCARB assessments are attached
to individual spatial features.

## 7. Open the atlas in ArcGIS Pro

1. In ArcGIS Pro, open **View → Catalog Pane**.
2. Right-click **Folders** and choose **Add Folder Connection**.
3. Select the repository's **data\processed** folder.
4. Expand **unified_storage**, then expand the dated GeoPackage.
5. Drag **storage_features** and **administrative_features** onto the map.
6. Drag **storage_units** and **storage_assessments** onto the map. They appear
   under **Standalone Tables**.

To add unit names and classifications to **storage_features**:

1. Right-click **storage_features**.
2. Choose **Joins and Relates → Add Join**.
3. Join **storage_features.storage_unit_id** to
   **storage_units.storage_unit_id**.

To add assessment fields, first check **assessment_scope**:

- For Atlantic and NATCARB rows where assessment_scope is **feature**, join on
  **storage_feature_id**.
- For BC rows where assessment_scope is **unit**, join on
  **storage_unit_id**.

A unit-scoped BC value can appear beside several map features. Do not sum that
repeated value across the features; it is one assessment for the logical unit.

## 8. Open the atlas in QGIS

1. Open **Layer → Add Layer → Add Vector Layer**.
2. Select the dated unified GeoPackage as the source.
3. Add **storage_features** and **administrative_features**.
4. In the Browser panel, expand the GeoPackage and add **storage_units** and
   **storage_assessments** as tables when needed.
5. Use **Layer Properties → Joins** with the same IDs and assessment-scope
   rules described for ArcGIS Pro.

All unified map layers use **EPSG:3978 — NAD83 / Canada Atlas Lambert**.

## 9. Optional Python check

With the virtual environment active, save this as a Python script or paste it
into a Python session to locate the newest atlas and list its layers:

    from pathlib import Path

    import geopandas as gpd

    packages = sorted(
        Path("data/processed/unified_storage").glob(
            "*_13_CanadaGeologicalStorageUnified_AV_v2.gpkg"
        )
    )
    if not packages:
        raise FileNotFoundError("Run canco2-build before this example.")

    package = packages[-1]
    print(package)
    print(gpd.list_layers(package).to_string(index=False))

    features = gpd.read_file(package, layer="storage_features")
    print(features.groupby(["source_dataset", "source_layer"]).size())

## 10. Return later

Open a terminal in the repository folder and reactivate the existing
environment:

    .venv\Scripts\Activate.ps1

Do not recreate **.venv** every time. To deactivate it:

    deactivate

For a deliberate clean data rebuild, remove the generated contents under
**data\raw** and **data\processed**, but retain those directories and their
**.gitkeep** files. Then run **canco2-build** again.

## Troubleshooting

### py or python is not recognized

Close and reopen the terminal after installing Python. On Windows, rerun the
installer and ensure the Python launcher and PATH option are enabled.

### canco2-build is not recognized

Confirm that **(.venv)** is visible, then run:

    python -m pip install -e .
    python scripts\build_all.py

### A download fails

Check the internet connection and run **canco2-build** again. Existing valid
downloads are reused where supported.

### A build fails after source data changes

Read the final error in the terminal before deleting anything. The workflow is
designed to stop when a provider changes an expected file or schema.

## Where to learn more

- [Data catalog](data-catalog.md): maps, source layers, and dataset meaning
- [Schema contract](schema.md): canonical tables and field definitions
- [Workflow guide](workflow.md): selective builds, validation, and reruns
- [NATCARB guide](datasets/natcarb.md): detailed NATCARB decomposition
- [Northeast BC guide](datasets/bc-storage-atlas.md): pool and aquifer details
