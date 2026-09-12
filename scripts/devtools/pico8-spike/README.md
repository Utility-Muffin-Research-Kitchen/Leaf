# Native PICO-8 device spike

You can use these fixtures to repeat the MLP1 Wayland experiment without
changing the installed launcher. They are development tools, not a Pak Rat
package or a supported emulator entry. The app route uses the existing generic
Apps input policy, so it does not qualify the protected controller roster.

Run the host checks without purchased files or a device:

```sh
python3 scripts/devtools/pico8-spike/check.py
```

For the device experiment, use the Raspberry Pi `pico8_64` and `pico8.dat`
from your purchased download. Verify the executable with the toolchain's
`scripts/verify-binary.sh`. Place the pair in primary `BIOS_PATH/PICO8/`.
Do not overwrite an existing installation or put the files in this repository.

Install `launch.sh` temporarily as
`APPS_PATH/mlp1/PICO8Spike.pak/launch.sh`. Copy `wget` to
`UMRK_RUNTIME_PATH/pico8-spike/bin/wget`. Both must be executable.
The adapter handles only the two wget argument forms observed in PICO-8 0.2.7.
It calls `UMRK_RUNTIME_PATH/pico8-spike/curl`, with private libraries in
`UMRK_RUNTIME_PATH/pico8-spike/lib/` and the device's CA bundle. You must supply
those development dependencies separately; they are not included here.
The experiment report records the exact files tested and their provenance.

The app always uses primary `USERDATA_PATH/pico8` for native state and
`RECORDINGS_PATH/PICO8` for captures. It refuses a source-rebound app environment.
It expects Leaf's configured source lists, with the primary source first.
This is not a production implementation of PATH-2 validation or native preflight.

With no `UMRK_RUNTIME_PATH/pico8-spike/cart-path` file, the app opens Splore at
primary `ROMS_PATH/PICO8`. To test a direct cart, write its absolute device path
as one line in `cart-path`. The wrapper selects the corresponding configured
ROM root, checks its card is mounted, and preserves the primary native home.
Use the fixture in a fresh `Leaf Native Spike` directory under `Roms/PICO8`
on each card. It creates `persistence-output.p8` beside itself and increments
`leaf_pico8_spike_v1` in the primary native home on each run.

Launch through `jawaka-platformctl` with the existing `launch-app` request:

```sh
"$UMRK_BIN_PATH/jawaka-platformctl" --socket "$UMRK_DAEMON_SOCKET" request \
  '{"type":"launch-app","pak_dir":"Apps/mlp1/PICO8Spike.pak"}'
```

For an ADB-driven request, terminate only the existing `jawaka-launcher`
frontend after the successful reply, matching the frontend's normal exit on
app launch. Keep `loong_pangu` and Weston running so Jawaka supervises the app
and restores Leaf. Do not request another app while a game or app is running.

For uipad, use `scripts/adb-uipad.sh install` and `start` before launching.
The synthetic pad is controller 1. PICO-8 ignores it for player 0 unless you
set its documented `merge_joysticks 2` setting while PICO-8 is stopped. Back up
the config first, and restore the setting after testing. This is a test setup,
not the final input policy. Allow queued uipad presses to finish before capturing.

Direct cart: **START > Shutdown**. Splore cart: **START > Exit to Splore**,
or **START > Options > Shutdown PICO-8** to return to Leaf. In the Splore
browser, select a cart and use **START > Options > Shutdown PICO-8**.
These paths were exercised with uipad; paired-controller qualification remains.

After testing, exit gracefully, stop uipad, and remove the temporary app,
its runtime directory, and the fixture directories you created. Preserve the
purchased files and native home. The runtime directory is temporary and does
not survive reboot; do not leave this app installed as though it were a
finished integration.
