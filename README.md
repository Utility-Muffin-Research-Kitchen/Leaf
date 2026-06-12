<p align="center">
  <img src=".github/social-preview.png" alt="Leaf — custom firmware for the Miniloong Pocket 1" width="760">
</p>

<p align="center">
  <a href="https://github.com/Utility-Muffin-Research-Kitchen/Leaf/releases"><img alt="release" src="https://img.shields.io/github/v/release/Utility-Muffin-Research-Kitchen/Leaf?color=7FB069&labelColor=0F160E&cacheSeconds=3600"></a>
  <a href="https://github.com/Utility-Muffin-Research-Kitchen/Leaf/releases"><img alt="downloads" src="https://img.shields.io/github/downloads/Utility-Muffin-Research-Kitchen/Leaf/total?color=7FB069&labelColor=0F160E&cacheSeconds=3600"></a>
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/github/license/Utility-Muffin-Research-Kitchen/Leaf?color=7FB069&labelColor=0F160E&cacheSeconds=3600"></a>
  <img alt="last commit" src="https://img.shields.io/github/last-commit/Utility-Muffin-Research-Kitchen/Leaf?color=7FB069&labelColor=0F160E&cacheSeconds=3600">
</p>

Leaf is the developer command surface for the UMRK launcher workspace. It owns
workspace bootstrap, cross-repo status/preflight, payload assembly, and SD-card
deployment. Product repos remain independent siblings and keep their own build
and package targets.

## Setup

Create a parent workspace, clone Leaf, then let Leaf clone the rest of the
sibling repos:

```sh
mkdir -p ~/dev/UMRK
cd ~/dev/UMRK
git clone https://github.com/Utility-Muffin-Research-Kitchen/Leaf.git
cd Leaf

make bootstrap
make -C ../mlp1-toolchain image
make doctor
make stage DEVICE=mlp1
```

By default Leaf treats its parent directory as the workspace root:

```text
~/dev/UMRK/
  Leaf/
  umrk-workspace/
  Catastrophe/
  Jawaka/
  Thing-File/
  ssh-server/
  CentralScrutinizer/
  Fugazi/
  retroarch-builds/
  Cores-spruce/
  mlp1-toolchain/
  miniloong-launcher-switcher/
  miniloong-adb-keeper/
```

For unusual checkout layouts, set `LEAF_WORKSPACE_DIR`:

```sh
LEAF_WORKSPACE_DIR=/Volumes/Storage/UMRK make status
```

## Commands

Run commands from the `Leaf` repo:

```sh
make bootstrap                              # clone any missing sibling repos
make doctor                                 # preflight: adb / docker / toolchain / device
make status                                 # git status across all siblings

make stage DEVICE=mlp1                      # full: launcher payload + all apps
make stage-refresh DEVICE=mlp1              # full stage, then restart Jawaka GUI
make refresh-jawaka DEVICE=mlp1             # restart Jawaka/Loong GUI stack only
make stage-jawaka DEVICE=mlp1               # launcher payload only
make stage-retroarch DEVICE=mlp1            # RetroArch binary + cores + info
make stage-emulator EMULATOR=drastic DEVICE=mlp1
make stage-app APP=ssh-server DEVICE=mlp1   # stage one app
make stage-app APP=Thing-File DEVICE=mlp1
make stage-app APP=CentralScrutinizer DEVICE=mlp1
make stage-app APP=Fugazi DEVICE=mlp1

make release-zips DEVICE=mlp1               # build end-user install + recovery ZIPs
make release-sd-zip DEVICE=mlp1             # build end-user install ZIP only
make release-recovery-zip DEVICE=mlp1       # build end-user recovery ZIP only
```

`make bootstrap` is idempotent. Existing sibling repos are reported as present
and left untouched. Missing repos are cloned into `Leaf/..`.

## End-User SD Install Package

Leaf can build root-extractable ZIPs for installing Leaf on a Miniloong Pocket
1 without requiring ADB first. This is the preferred path for making a device
installation package for end users.

From the `Leaf` repo:

```sh
make bootstrap
make -C ../mlp1-toolchain image
make release-zips DEVICE=mlp1
```

The release command builds missing MLP1 components, assembles the launcher and
platform payload, packages standalone emulators and first-party apps, and asks
`miniloong-launcher-switcher` to generate the stock `loong_upgrade` install and
recovery payloads.

Output is written to:

```text
build/release/leaf-mlp1-sd-<release_id>.zip
build/release/leaf-mlp1-recovery-<release_id>.zip
```

`<release_id>` defaults to the current date plus the Leaf git short SHA. To
choose it explicitly:

```sh
make release-zips DEVICE=mlp1 RELEASE_ID=2026-06-05-test1
```

The install ZIP is extracted directly to the SD-card root. It must not be
placed inside another folder. The SD card should be FAT32 or ext4; do not use
exFAT because the MLP1 stock update path ignores exFAT media.

End-user flow:

1. Extract `leaf-mlp1-sd-<release_id>.zip` to the SD-card root.
2. Boot the MLP1 with the SD card inserted.
3. Wait on the stock update screen while the installer runs. The progress
   indicator may sit at 50 percent while files are copying.
4. Wait for the device to reboot by itself.
5. Boot normally with the SD card inserted; Leaf should start automatically.

The install package does not silently enable or pin ADB. ADB can be enabled
later from Leaf/Jawaka settings.

To return a device to stock boot without ADB, extract
`leaf-mlp1-recovery-<release_id>.zip` to the SD-card root and boot the device
once with that card inserted. Wait for the device to reboot by itself.
Recovery removes the Leaf hook/session and leaves SD-card user content intact.

## Ownership

Leaf owns deployment and orchestration:

- Bootstrap and repo discovery.
- Cross-repo status.
- Environment and device preflight.
- Launcher payload assembly.
- SD-card path resolution.
- ADB staging.
- Activation marker control.
- Launcher restart and log-tail helpers.
- End-user SD install/recovery ZIP generation.

Sibling repos own their build/package outputs:

- `Jawaka` builds launcher binaries.
- `Catastrophe` builds shared assets.
- `retroarch-builds` builds/packages RetroArch.
- `Cores-spruce` builds libretro cores and info files.
- App repos package their `.pak` directories.
- `mlp1-toolchain` owns the cross-compile Docker image.

The runtime stock-firmware switcher mechanism remains in
`miniloong-launcher-switcher`.

## SD Layout

Leaf stages launcher-owned internals under one hidden SD root:

```text
$SDCARD_PATH/.system/leaf/platforms/mlp1/enabled
$SDCARD_PATH/.system/leaf/platforms/mlp1/launcher/env.sh
$SDCARD_PATH/.system/leaf/platforms/mlp1/launcher/bin/...
$SDCARD_PATH/.system/leaf/platforms/mlp1/bin/
$SDCARD_PATH/.system/leaf/platforms/mlp1/cores/
$SDCARD_PATH/.system/leaf/platforms/mlp1/emulators/
$SDCARD_PATH/.system/leaf/platforms/mlp1/state/
$SDCARD_PATH/.system/leaf/platforms/mlp1/state/adb-enabled
$SDCARD_PATH/.system/leaf/platforms/mlp1/userdata/logs/
$SDCARD_PATH/.system/leaf/shared/userdata/
```

`state/adb-enabled` is Jawaka's durable request for the Leaf init hook to
restore the stock ADB pin at boot. The launcher activation marker is separate:
`platforms/mlp1/enabled`.

User-facing content folders remain at the SD root:

```text
Roms/
Images/
Apps/
  mlp1/<Name>.pak/
  shared/<Name>.pak/
BIOS/
Saves/
States/
Cheats/
```

`Apps/` is a namespace root. Leaf stages native apps under `Apps/<platform>/`
and wrapper/runtime-delegating apps under `Apps/shared/`; flat
`Apps/<Name>.pak/` entries are not part of the Jawaka discovery contract.

The current first-party app policies are:

```text
ssh-server        -> Apps/mlp1/SSHServer.pak/
Thing-File        -> Apps/mlp1/Thing-File.pak/
CentralScrutinizer -> Apps/mlp1/CentralScrutinizer.pak/
Fugazi            -> Apps/mlp1/Fugazi.pak/
retroarch-builds  -> Apps/shared/RetroArch.pak/
```

Standalone game emulator payloads are staged under
`.system/leaf/platforms/mlp1/emulators/`. PPSSPP is built from the UMRK
`PPSSPP-spruce` sibling repo. DraStic is packaged from the local
`steward-fu-nds` sibling repo: Leaf bundles the cross-built steward SDL2 custom
menu stack with the prebuilt `drastic64` binary, keeps runtime state under
`state/drastic/`, and runs it through `SDL_VIDEODRIVER=NDS`. Single-emulator ADB
staging also refreshes the platform defaults that Jawaka scans for packaged
standalone launch targets. DraStic's in-game menu is handled by the steward
custom menu, with Jawaka passing the MLP1 Menu button through to the emulator.

This is a hard cutover from the old `umrk-launcher`, `UMRK`, `.umrk`,
`.userdata`, and `.umrk-launcher` layout. Leaf does not migrate or delete old
folders automatically.
