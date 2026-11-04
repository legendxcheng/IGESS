-- Local diagnostic only. Uses recorded inventory identities/levels, fresh archive
-- defaults for other systems, synthetic hatch weight=1. No historical replay.
package.path = './?.lua;./proj/?.lua;./proj/?/init.lua;' .. package.path
local Json = require('simulation.Json')
local f = assert(io.open(arg[1], 'rb'))
local inventories = Json.Decode(f:read('*a')); f:close()
assert(require('simulation.SnapshotTables').Install(arg[2]))
require('Script.Core.Logger'):SetSink(function() end)
local Schema = require('Script.Domain.Player.PlayerArchiveSchema')
local Economy = require('Script.Domain.Fishing.FishEconomyRules')
local rules = assert(Economy.Build())
local Host = require('simulation.Host')
local result = { note='Diagnostic local CPU seconds; recorded final fish identities/levels, synthetic hatch weights, otherwise fresh archive. Not full-run attribution.', passes={} }
local function bench(fn, n)
    local started = os.clock()
    for _=1,n do assert(fn()) end
    return (os.clock()-started)/n
end
for pass=1,3 do
local order = pass==2 and {'whale_plain','whale_low_reference','whale','permanent','free'}
    or {'free','permanent','whale','whale_low_reference','whale_plain'}
local rows={}
for _, tag in ipairs(order) do
    local items = inventories[tag] or inventories.whale
    items = Json.Decode(Json.Encode(items))
    if tag == 'whale_low_reference' then
        for _, item in ipairs(items) do if item.fishId ~= 2004 then item.level=1 end end
    elseif tag == 'whale_plain' then
        for _, item in ipairs(items) do if item.fishId == 2004 then item.fishId=101 end end
    end
    local state = assert(Schema.New(0))
    state.fish.items=items
    local maxId=0
    for _,item in ipairs(items) do maxId=math.max(maxId,item.instanceId) end
    state.fish.nextInstanceId=maxId+1
    state.fishHall.upgradeLevel=25
    local valid, code, path = Schema.Validate(state)
    assert(valid, tostring(code)..':'..tostring(path))
    local session, why=Host.Open({startAt=0, initialState=state, fastAdvance=true})
    assert(session, why)
    assert(session:Query());assert(session:QueryActions())
    local row={}
    row.production_snapshot=bench(function() return Economy.CalculateProductionSnapshot(rules,items) end,100)
    row.query_cached_inventory=bench(function() return session:Query() end,40)
    row.query_actions_cached=bench(function() return session:QueryActions() end,100)
    local t=0
    row.advance_one_second=bench(function() t=t+1;return session:AdvanceTo(t) end,40)
    rows[tag]=row
    assert(session:GoOffline())
end
result.passes[pass]=rows
end
io.write(Json.Encode(result))
