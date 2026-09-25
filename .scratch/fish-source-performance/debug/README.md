# Diagnostic artifacts only

These probes and captured profiles are excluded from performance comparisons.
`lua_probe.lua` is injected only into a disposable frozen host by an explicit
`lua-profile` tag. The probe changes that host after its ordinary fingerprint
was computed; the resulting run is diagnostic and must not be treated as a
fingerprinted production baseline. No probe is installed in either runtime.

`reference-host.lua.txt` preserves the pre-change host for manual inspection.
The same source is in the Fish repository's pre-change HEAD; the file is not
loaded by the simulator. Binary `.prof` files are local diagnostic evidence.
