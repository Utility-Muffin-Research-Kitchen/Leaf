# PPSSPP benchmark input traces

Input traces drive repeatable PSP controls through PPSSPP's debugger during
benchmark warm-up and measurement. They never contain or install game data.

Pass a trace directly:

```sh
make benchmark-ppsspp \
  ROM="/device/path/game.iso" \
  CORE=vulkan \
  PRESET=performance \
  TRACE=scripts/ppsspp-input-traces/god-of-war-chains-opening.json
```

Schema 1 fields:

- `name`: human-readable trace name.
- `game_id`: optional PPSSPP game ID. A mismatch fails before input is sent.
- `description`: optional evidence description.
- `events`: non-empty array sorted by the harness using `at`, in seconds from
  debugger connection.
- `event`: `input.buttons.press`, `input.buttons.send`, or
  `input.analog.send`.
- `repeat_every`: optional positive repetition period in seconds.
- `repeat_until`: optional final repetition time. The benchmark horizon is
  always an upper bound.

Late input is skipped rather than replayed in a burst after a debugger
reconnection. At cleanup, the harness centers both analog sticks and releases
every button named by the trace before terminating PPSSPP.
