"""Exact differential arithmetic corpus, run against frozen and candidate Lua."""
import json
import random
import subprocess
import sys
from pathlib import Path

root = Path('.tmp/fish-query-perf').resolve()
rng = random.Random(38271)
values = ['0', '1', '-1', '9', '10', '9999999', '10000000',
          '9'*256, '1'+'0'*255, '1e-1000000', '1e1000000']
for width in [1, 6, 7, 8, 14, 15, 30, 128, 255, 256]:
    for _ in range(6):
        values.append(('-' if rng.randrange(2) else '') + str(rng.randrange(1,10))
                      + ''.join(str(rng.randrange(10)) for _ in range(width-1))
                      + 'e' + str(rng.randrange(-40,41)))
pairs = [(a,b) for a in values for b in ['1','2','3','7','10','9999999','10000000','1e-30','-3']]
pairs += [(rng.choice(values), rng.choice(values)) for _ in range(300)]
lua = r'''
package.path='./?.lua;./proj/?.lua;'..package.path
if arg[2] == 'double' then
    local native = tonumber
    tonumber = function(...)
        local value = native(...)
        return value and value + 0.0 or nil
    end
end
local B=require('Script.Core.BigNumber')
local J=require('simulation.Json')
local cases=assert(J.Decode(assert(io.open(arg[1],'rb')):read('*a')))
local results={}
for _,pair in ipairs(cases) do
    local a,b=B.new(pair[1]),B.new(pair[2])
    for _,op in ipairs({'add','sub','mul','div'}) do
        for _,precision in ipairs(op=='div' and {1,7,64,256} or {256}) do
            local ok,value=pcall(a[op],a,b,precision)
            results[#results+1]=ok and {value._sign,value._coeff,value._exp} or 'error'
        end
    end
end
io.write(J.Encode(results))
'''
(root/'arithmetic-cases.json').write_text(json.dumps(pairs), encoding='utf-8')
(root/'arithmetic-probe.lua').write_text(lua, encoding='utf-8')
outputs = []
for variant in ['baseline','candidate']:
    out = subprocess.run(['lua55',str(root/'arithmetic-probe.lua'),str(root/'arithmetic-cases.json'),
                          'double' if '--double' in sys.argv else 'native'],
                         cwd=root/(variant+'-source'), capture_output=True, check=True).stdout
    (root/(variant+('-double' if '--double' in sys.argv else '')+'-arithmetic.json')).write_bytes(out)
    outputs.append(json.loads(out))
assert outputs[0] == outputs[1], next((i for i,(a,b) in enumerate(zip(*outputs)) if a!=b), 'length')
print(f'{len(outputs[0])} exact arithmetic results match', flush=True)
