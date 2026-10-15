# SDL2 notice

RetroArch on the Miniloong Pocket 1 loads its own copy of
[SDL](https://www.libsdl.org/) 2.28.5 from
`platforms/mlp1/lib/retroarch/libSDL2-2.0.so.0` instead of the one in the
device firmware. The launcher, the menus and the standalone emulators keep using
the firmware's SDL.

This copy is altered. It carries two small fixes to SDL's Wayland video code:
one that upstream SDL released in 2.30.2, backported to 2.28.5
([libsdl-org/SDL@a6b684d](https://github.com/libsdl-org/SDL/commit/a6b684d05a)),
and one of Leaf's own. Without them, unplugging HDMI during a RetroArch game
crashes or freezes RetroArch before it writes your in-game save.

SDL is distributed under the zlib license, reproduced verbatim in `SDL2.txt`.
The unmodified source is the upstream `SDL2-2.28.5.tar.gz` release. The patch
and the exact build recipe are in
[retroarch-builds](https://github.com/Utility-Muffin-Research-Kitchen/retroarch-builds)
(`patches/mlp1/sdl2/` and `build-mlp1-sdl2.sh`), and every release records the
source and patch checksums in `platforms/mlp1/bin/retroarch.build-manifest.json`.
