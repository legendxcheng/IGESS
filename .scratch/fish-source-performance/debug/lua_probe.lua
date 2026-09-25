-- Diagnostic-only instrumentation injected into the disposable frozen host.
local probeStats = { operations = {}, samples = {}, encodeSeconds = 0, bytes = 0 }
local dispatchOriginal = dispatch
dispatch = function(request)
    local start = os.clock()
    local values = table.pack(dispatchOriginal(request))
    local entry = probeStats.operations[request.op] or { count = 0, seconds = 0 }
    entry.count = entry.count + 1
    entry.seconds = entry.seconds + os.clock() - start
    probeStats.operations[request.op] = entry
    return table.unpack(values, 1, values.n)
end
local encodeOriginal = Json.Encode
Json.Encode = function(value)
    local start = os.clock()
    local encoded = encodeOriginal(value)
    probeStats.encodeSeconds = probeStats.encodeSeconds + os.clock() - start
    probeStats.bytes = probeStats.bytes + #encoded
    return encoded
end
debug.sethook(function()
    local seen = {}
    for level = 2, 24 do
        local info = debug.getinfo(level, "S")
        if not info then break end
        local key = info.short_src .. ":" .. info.linedefined
        if not seen[key] then
            probeStats.samples[key] = (probeStats.samples[key] or 0) + 1
            seen[key] = true
        end
    end
end, "", 10000)
