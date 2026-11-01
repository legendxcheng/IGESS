-- Standalone CLI diagnostic only; every wrapped operation still runs normally.
package.path='./?.lua;./proj/?.lua;'..package.path
local Archive=require('Script.Application.PlayerArchiveService')
local Schema=require('Script.Domain.Player.PlayerArchiveSchema')
local Json=require('simulation.Json')
local snapshots,validations=0,0
local get,validate=Archive.GetSnapshot,Schema.Validate
Archive.GetSnapshot=function(...) snapshots=snapshots+1;return get(...) end
Schema.Validate=function(...) validations=validations+1;return validate(...) end
local session=assert(require('simulation.Host').Open({startAt=0,randomSeed=37,fastAdvance=true}))
local results={}
for i=1,2 do
    snapshots,validations=0,0
    assert(session:Query())
    results[i]={snapshots=snapshots,validations=validations}
end
print(Json.Encode(results))
