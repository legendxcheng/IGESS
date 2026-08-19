---
name: publish-gamebalancer
description: Prepare, validate, and optionally publish a new GameBalancer execution-toolkit version from IGESS. Use when the user asks to update, rebuild, export, release, version-bump, commit, or push E:\GameBalancer, or to deliver new IGESS Fish runtime, scenario, configuration, or Luban schema support to execution planners.
---

# Publish GameBalancer

Prepare releases from `E:\IGESS` into the separate distribution repository at
`E:\GameBalancer`. Keep production JSON at
`E:\fish-oasis\igess_export\json` absolutely read-only.

## Classify the update

- Do not publish a toolkit for value-only `.xlsx`/JSON changes. The planner can
  export JSON and rerun the current tool.
- Publish a new toolkit when IGESS code, Fish scenarios/configuration, report
  behavior, or the generated Luban schema contract changes.

## Choose the version

Read `E:\GameBalancer\operator-manifest.json`. Use a user-specified greater
semantic version, or increment the patch component by one. Never reuse or
decrease a version because cross-tool-version comparison is prohibited.

## Prepare and test

1. Ask the user to close the running workbench. Check both repositories with
   `git status --short`; preserve every existing change and never clean/reset.
2. If GameBalancer is dirty before preparation, stop and inspect it. Use
   `-AllowDirtyDistribution` only when deliberately resuming a previously
   reviewed failed preparation.
3. Run the bundled script from `E:\IGESS`:

```powershell
& .\.codex\skills\publish-gamebalancer\scripts\prepare-release.ps1 `
  -Version 0.5.3
```

The script runs Fish and toolkit regression tests, calls the official exporter,
audits the sourceless delivery, submits `smoke` through the real local workbench
form using production JSON, verifies the report, and proves the JSON files did
not change. It deliberately does not commit or push.

If preparation fails, preserve the failed run as evidence, diagnose the actual
boundary, and do not publish. Never patch generated `.pyc`, bundle files, or the
delivery manifest by hand; fix IGESS and rerun the exporter.

## Review the candidate

Review at least:

```powershell
git -C E:\GameBalancer status --short
git -C E:\GameBalancer diff --stat
git -C E:\GameBalancer diff -- start.bat operator-manifest.json .igess-delivery-manifest.json
```

Recompiled `.pyc` files changing is expected. Require zero `.py`, `.pyi`, source
maps, tests, source paths, or unexpected files. Confirm the displayed version,
successful run ID, report HTTP 200, loopback binding, and unchanged input hashes.

If IGESS was dirty, state that the candidate contains uncommitted source. Do not
commit or push until the user explicitly accepts that fact or commits the source
repository first.

## Publish only with authority

When the user explicitly asks to publish or push and the review is clean:

```powershell
git -C E:\GameBalancer add -A
git -C E:\GameBalancer commit -m "feat: publish GameBalancer 0.5.3"
git -C E:\GameBalancer push
```

Use a `fix:` message when the release is specifically a defect correction. Then
verify that the local HEAD equals `origin/master` and the distribution worktree
is clean. Do not commit unrelated IGESS changes as part of the distribution
release.

Report the version, commit, test counts, end-to-end run ID, input-read-only
result, and the planner instruction: close the tool, run `git pull`, then launch
`start.bat`.
