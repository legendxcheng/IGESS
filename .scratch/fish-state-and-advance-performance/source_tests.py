"""Run source seam tests with durable logs instead of warning floods."""
from pathlib import Path
import json
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
variant=sys.argv[1]
root=Path('.tmp/fish-state-advance')/f'{variant}-source'
names=sys.argv[2:] or [
    'simulation_host_test.lua','simulation_query_observation_test.lua',
    'simulation_query_validation_test.lua','simulation_observation_changes_test.lua',
    'simulation_advance_boundaries_test.lua','simulation_blocked_eggs_test.lua',
    'simulation_eggs_test.lua','simulation_tides_test.lua','simulation_natural_landing_test.lua',
    'fish_inventory_complete_query_test.lua','fish_production_duplicate_projection_test.lua',
    'big_number_arithmetic_test.lua','simulation_json_encoding_test.lua',
]
logs=HERE/'logs';logs.mkdir(exist_ok=True)
rows=[]
for name in names:
    started=time.perf_counter()
    log=logs/f'{variant}-{name}.log'
    with log.open('wb') as out:
        result=subprocess.run(['lua55',f'tests/{name}'],cwd=root,stdout=out,stderr=subprocess.STDOUT)
    row=dict(test=name,exit_code=result.returncode,seconds=time.perf_counter()-started,log=str(log))
    rows.append(row);print(json.dumps(row),flush=True)
    if result.returncode:
        print(log.read_text(encoding='utf-8',errors='replace')[-2000:],flush=True)
(logs/f'{variant}-summary.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
if any(row['exit_code'] for row in rows): raise SystemExit(1)
