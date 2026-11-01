-- DIAGNOSTIC ONLY: isolated numerical host, never installed in game/PIE/DS.
local perf, stack, combinations, sampled, owners, recursive = {}, {}, {}, {}, {}, {}
local perfOp, totalSamples = 'startup', 0
local active = {}
local function accumulate(target, key, elapsed, own)
    local row = target[key] or {count=0, seconds=0, self_seconds=0}
    row.count=row.count+1; row.seconds=row.seconds+elapsed
    row.self_seconds=row.self_seconds+own; target[key]=row
end
local function timed(label, fn, ...)
    -- Only time the outer call of recursive clone/copy/compare routines.
    if active[label] then
        recursive[label]=(recursive[label] or 0)+1
        return fn(...)
    end
    active[label]=true
    local parent=stack[#stack]
    local owner=label:sub(1,8)=='service.' and label or (parent and parent.owner or 'root')
    local frame={child=0,owner=owner}; stack[#stack+1]=frame
    local started=os.clock()
    local values=table.pack(xpcall(fn,debug.traceback,...))
    local elapsed=os.clock()-started
    stack[#stack]=nil; active[label]=nil
    if parent then parent.child=parent.child+elapsed end
    accumulate(perf,perfOp..'/'..label,elapsed,elapsed-frame.child)
    accumulate(owners,perfOp..'|'..owner..'|'..label,elapsed,elapsed-frame.child)
    if not values[1] then error(values[2],0) end
    return table.unpack(values,2,values.n)
end
_G.__fishPerfTimed=timed
local watched={
 ['Script.Application.PlayerArchiveService']={'GetSnapshot','RunTransaction'},
 ['Script.Domain.Player.PlayerArchiveSchema']={'Validate','Clone'},
 ['Script.Domain.Fishing.FishInventoryQuery']={'Build'},
 ['Script.Domain.Fishing.FishEconomyRules']={'GetLevelSnapshot','CalculateLevelRate','CalculateUpgradeCost','CalculateSellPrice','CalculateProductionSnapshot'},
 ['Script.Domain.Fishing.FishHallRules']={'CalculateRateSnapshot'},
 ['Script.Domain.Fishing.ThrowOutcomeResolver']={'QueryLuck','Resolve'},
 ['Script.Domain.Fishing.ThrowLuckMapping']={'MapStrengthToFishLuck','MapTorpedoPowerToTrashLuck'},
 ['Script.Application.PlayerEconomyService']={'SettleProduction'},
 ['simulation.Json']={'Encode','Decode'},
}
local seen, seenServices={},setmetatable({},{__mode='k'})
local originalRequire=require
require=function(name)
    local result=originalRequire(name)
    if watched[name] and not seen[name] then
        seen[name]=true
        for _,method in ipairs(watched[name]) do
            local original=result[method]
            if type(original)=='function' then
                local label=name..'.'..method
                result[method]=function(...)
                    if name=='Script.Domain.Fishing.FishEconomyRules'
                        and (method=='GetLevelSnapshot' or method=='CalculateLevelRate') then
                        local rules,fishId,mutationId,level=...
                        local fish=type(rules)=='table' and rules.fishById and rules.fishById[fishId]
                        local kind=fish and fish.productionMode=='best_hall_fish' and 'beast' or 'ordinary'
                        local group=method..'/'..kind
                        local row=combinations[group] or {calls=0,keys={},ruleKeys={}}
                        row.calls=row.calls+1
                        local key=tostring(fishId)..'/'..tostring(mutationId)..'/'..tostring(level)
                        row.keys[key]=(row.keys[key] or 0)+1
                        row.ruleKeys[tostring(rules)..'/'..key]=true
                        combinations[group]=row
                    end
                    return timed(label,original,...)
                end
            end
        end
    end
    if name=='simulation.Query' and not seen[name] then
        seen[name]=true
        local originalBuild=result.Build
        result.Build=function(context,services,rules)
            for serviceName,service in pairs(services) do
                local method=serviceName=='throw' and 'QueryLuck' or 'Query'
                local original=service[method]
                if type(original)=='function' and not seenServices[service] then
                    seenServices[service]=true
                    local label='service.'..serviceName..'.'..method
                    service[method]=function(...) return timed(label,original,...) end
                end
            end
            local query=originalBuild(context,services,rules)
            for _,method in ipairs({'Query','QueryActions'}) do
                local original=query[method]
                query[method]=function(...) return timed('pipeline.'..method,original,...) end
            end
            return query
        end
    end
    return result
end
debug.sethook(function()
    totalSamples=totalSamples+1
    local info=debug.getinfo(2,'Sln')
    if info then
        local key=perfOp..'|'..info.source..':'..info.currentline..'|'..(info.name or '?')
        sampled[key]=(sampled[key] or 0)+1
    end
end,'',100000)
