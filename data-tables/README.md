# Sample Luban Source Tables

`data-tables/Datas` contains lightweight Luban-style source workbooks for the sample economy.

They use the minimum marker-row layout:

- Row 1: `##var`
- Row 2: `##`
- Row 3: `##type`
- Row 4+: data

Regenerate them with:

```powershell
.\.venv\Scripts\python tools/create_sample_luban_sources.py
```

The simulator still reads exported JSON from `examples/shelldiver_v0/luban_exports`; these workbooks are the authoring source/template side of the workflow.
