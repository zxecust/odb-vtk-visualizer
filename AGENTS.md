# Project structure

- Keep user-facing Python GUI entry points in the project root.
- Put Python scripts called by those entry points in `script/`.
- ODB Exporter has two scripts: `odb_exporter.py` for the GUI and
  `script/odb_export_backend.py` for ODB inspection, upgrading, node ordering,
  CSV export and the GUI event protocol. Keep its backend self-contained.
- The GUI runs in ordinary Python; the backend runs in Abaqus Python and must
  remain compatible with Python 2 and Python 3. Keep Abaqus imports lazy so the
  backend can be imported for checks without an Abaqus installation.
