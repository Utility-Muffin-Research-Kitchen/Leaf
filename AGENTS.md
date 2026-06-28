# Leaf Agent Instructions

Leaf is the deploy/orchestration repo for the UMRK launcher workspace.

When the private sibling docs repo is present, use it for cross-repo
architecture, ownership boundaries, runtime path conventions, and device
details:

```text
../umrk-workspace/AGENTS.md
../umrk-workspace/docs/runtime-paths.md
../umrk-workspace/plans/leaf-repo-split-and-sd-layout-cleanup.md
```

Keep product builds in their owning repos. Leaf may call those build/package
targets, assemble deploy payloads, and stage files to a device, but it should
not reimplement Jawaka, Catastrophe, RetroArch, core, app, or toolchain builds.

Default workspace layout is sibling-based:

```text
UMRK/
  Leaf/
  Catastrophe/
  Jawaka/
  Thing-File/
  ssh-server/
  N64-standalone/
  retroarch-builds/
  Cores-spruce/
  mlp1-toolchain/
  miniloong-launcher-switcher/
  miniloong-adb-keeper/
  umrk-workspace/      # optional internal docs/plans, only with access
```

Use `LEAF_WORKSPACE_DIR` only for unusual local layouts.
