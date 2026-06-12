# Emulator core licenses

Leaf release ZIPs include prebuilt libretro cores and standalone emulators. Each
is the work of its respective authors and is distributed under its own license;
the full, verbatim license text for every one ships alongside this file in
`cores/<core>.txt`.

Leaf is free software and is distributed at no cost. Several cores below are
licensed for **non-commercial use only** - Leaf and these cores must never be
sold, bundled with hardware for sale, or otherwise used commercially.

Corresponding source code for every core is publicly available at the upstream
listed below. Libretro cores are built unmodified from these sources by
[Cores-spruce](https://github.com/Utility-Muffin-Research-Kitchen/Cores-spruce)
(forked from spruceOS's build lane, downstream of
[libretro-super](https://github.com/libretro/libretro-super)). Standalone
emulators may be either built by their owning UMRK sibling repo or repackaged
from the named upstream release asset.

| Core | License | Upstream source |
|---|---|---|
| dosbox_pure | GPL-2.0 | https://github.com/libretro/dosbox-pure |
| drastic (standalone) | LGPL-2.1 | https://github.com/steward-fu/nds |
| easyrpg | GPL-3.0 | https://github.com/EasyRPG/Player |
| fake08 | MIT | https://github.com/jtothebell/fake-08 |
| fbalpha2012 | FB Alpha (non-commercial) | https://github.com/libretro/fbalpha2012 |
| fbneo | FB Neo (non-commercial) | https://github.com/libretro/FBNeo |
| fceumm | GPL-2.0 | https://github.com/libretro/libretro-fceumm |
| flycast | GPL-2.0 | https://github.com/flyinghead/flycast |
| gambatte | GPL-2.0 | https://github.com/libretro/gambatte-libretro |
| genesis_plus_gx | Genesis Plus GX (non-commercial) | https://github.com/libretro/Genesis-Plus-GX |
| gw | zlib | https://github.com/libretro/gw-libretro |
| handy | zlib | https://github.com/libretro/libretro-handy |
| mame | GPL-2.0+ | https://github.com/libretro/mame |
| mame2003_plus | MAME (legacy, non-commercial) | https://github.com/libretro/mame2003-plus-libretro |
| mame2010 | MAME (legacy, non-commercial) | https://github.com/libretro/mame2010-libretro |
| mednafen_ngp | GPL-2.0 | https://github.com/libretro/beetle-ngp-libretro |
| mednafen_pce_fast | GPL-2.0 | https://github.com/libretro/beetle-pce-fast-libretro |
| mednafen_wswan | GPL-2.0 | https://github.com/libretro/beetle-wswan-libretro |
| mgba | MPL-2.0 | https://github.com/libretro/mgba |
| mupen64plus_next | GPL-2.0 | https://github.com/libretro/mupen64plus-libretro-nx |
| pcsx_rearmed | GPL-2.0 | https://github.com/libretro/pcsx_rearmed |
| ppsspp (standalone) | GPL-2.0+ | https://github.com/hrydgard/ppsspp |
| prosystem | GPL-2.0 | https://github.com/libretro/prosystem-libretro |
| snes9x | Snes9x (non-commercial) | https://github.com/libretro/snes9x |
| stella2014 | GPL-2.0 | https://github.com/libretro/stella2014-libretro |
| swanstation | GPL-3.0 | https://github.com/libretro/swanstation |
| yabasanshiro | GPL-2.0 | https://github.com/libretro/yabause |

Leaf never includes game ROMs or proprietary console BIOS files; users must
supply their own where an emulator requires them. RetroArch itself is GPL-3.0
(https://github.com/libretro/RetroArch).
