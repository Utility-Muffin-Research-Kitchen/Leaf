# Leaf Agent Instructions

Leaf is the deploy/orchestration repo for the UMRK launcher workspace.

For cross-repo architecture, ownership boundaries, runtime path conventions, and
device details, read the sibling docs repo first:

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
  umrk-workspace/
  Catastrophe/
  Jawaka/
  Thing-File/
  ssh-server/
  retroarch-builds/
  Cores-spruce/
  mlp1-toolchain/
  miniloong-launcher-switcher/
  miniloong-adb-keeper/
```

Use `LEAF_WORKSPACE_DIR` only for unusual local layouts.
