# Bundled asset licenses

Beyond the emulator cores (see `CORES.md`), Leaf bundles artwork and fonts. Each
is the work of its respective authors and is distributed under its own license.
The same summary is shown on-device under **Menu > Info > Device** and at
https://leaf.game/credits.

| Asset | Author / source | License |
|---|---|---|
| Cover Flow console art (icons in the `Jawaka-Coverflow` theme) | Evan Amos - Vanamo Online Game Museum / Wikimedia Commons | Public Domain |
| Default system icons (libretro Systematic pack) | libretro team and contributors | CC BY-SA 4.0 |
| Grid View system wordmarks (`res/grid_wordmarks/`) | System makers' logos, redrawn or adapted by UMRK; EasyRPG Team | Per file: Public Domain (PD-textlogo), CC0 1.0, CC BY-SA 4.0 (EasyRPG), SIL OFL 1.1 (Lexend glyphs); see below |
| Sample theme system logo cards (`Themes/Sample/grid/icons/`) | System makers' logos on white cards by UMRK; Jean Marc Gimenez (ScummVM); EasyRPG Team | Per file: Public Domain (PD-textlogo), CC0 1.0, CC BY-SA 3.0 (ScummVM), CC BY-SA 4.0 (EasyRPG), SIL OFL 1.1 (Lexend glyphs); see below |
| UI fonts (Space Grotesk, Inter, Rounded M+, Nunito, Baloo 2, Fredoka, Lexend, IBM Plex Sans, Noto Sans, Source Han Sans, Leaf Han Sans JP) | respective type designers; Leaf Han Sans JP is Adobe's Source Han Sans, subset and renamed by UMRK | SIL OFL 1.1 |
| Keyboard glyph icons (Nerd Fonts) | Nerd Fonts contributors | MIT |
| RetroArch menu artwork (`platforms/mlp1/assets/`, Ozone and XMB Monochrome) | libretro team and contributors | CC BY 4.0 |
| RetroArch menu font (Inter UI, in `assets/ozone/`) | The Inter UI project authors | SIL OFL 1.1 |
| RetroArch icon-theme font (M+ 1p, in `assets/xmb/monochrome/`) | M+ FONTS PROJECT | M+ Free License |
| RetroArch Chinese fallback font (Droid Sans Fallback) | Ascender Corporation / Google | Apache 2.0 |
| RetroArch Korean fallback font (Spoqa Han Sans) | Spoqa | SIL OFL 1.1 |
| RetroArch Arabic/Persian, Thai and OSD fonts (DejaVu Sans, Waree, DejaVu Sans Mono) | Bitstream, Inc.; DejaVu and TLWG contributors | Bitstream Vera license; project changes public domain |

**Cover Flow console art** - photographs of video game hardware released to the
public domain by Evan Amos (https://commons.wikimedia.org/wiki/User:Evan-Amos).
The images were background-removed (transparent alpha) and renamed to Jawaka
short codes for the theme; full-resolution originals are kept in the UMRK
`umrk-assets` repository. Per-file note ships alongside the assets in
`res/themes/Jawaka-Coverflow/system_icons/LICENSE-ASSETS.md`.

**Default system icons** - from the libretro Systematic asset pack
(https://github.com/libretro/retroarch-assets, `xmb/systematic/png/`), CC BY-SA
4.0. Per-file note ships in `res/system_icons/LICENSE-ASSETS.md`.

**Grid View system wordmarks** - white system logos for the Grid games view,
tinted to the theme's text color. The 24 added in September 2026 are documented
per file in `res/grid_wordmarks/INVENTORY-SOURCE.md` (sources, changes, export
SHA-256), with exact download records in `SOURCE-RECORDS.json`; PC98 is
documented in `res/grid_wordmarks/WORDMARK-SOURCE.md`. 32X, MD32X, ATOMISWAVE,
FDS and PC98 derive from Wikimedia Commons vectors designated PD-textlogo, and
AMIGA, COLECO, GW, VB and VECTREX reuse the Commons sources recorded for the
Sample theme cards. EASYRPG adapts the EasyRPG Team's official vector under its
CC BY-SA 4.0 branding license (https://blog.easyrpg.org/2023/04/); the
adaptation is also CC BY-SA 4.0. ARCADE and PORTS are original UMRK lettering
dedicated to CC0 1.0, drawn from outlined Lexend Bold glyphs (SIL OFL 1.1,
license shipped as `res/grid_wordmarks/Lexend-OFL.txt`); the MAME year labels
and the Atomiswave TM suffix use the same glyphs. DOS, LYNX, NEOGEO, NGP, NGPC,
PCECD, SATURN, WS, WSC and the MAME letterform come from Dan Patrick's console
logo collection (mirrored at https://github.com/PRO100BYTE/console-logos),
which attributes the logos to their makers and grants no license over them;
its README ships unmodified as `console-logo-mirror-README.md`. NAOMI comes
from a Worldvectorlogo vector. The original 18 wordmarks (ATARI2600, DC, FC,
GB, GBA, GBC, GG, MAME, MD, MS, N64, NDS, PCE, PS, PSP, SEGACD,
SEVENTYEIGHTHUNDRED, SFC) have no per-file source note yet. System names and
logos remain their owners' trademarks and identify the systems; no rights are
claimed in them and no endorsement is implied.

**Sample theme system logo cards** - 512x512 logo cards on a white field for
the bundled Sample Grid theme (Jawaka `res/user_themes/Sample/`, staged to
`Themes/Sample/`). Per-file note ships in
`Themes/Sample/grid/icons/GRID-ICON-SOURCE.md`, with Commons revision records
in `commons.json` beside it. It covers eleven added cards (AMIGA, ARCADE,
COLECO, EASYRPG, GW, PC98, PICO8, PORTS, SCUMMVM, VB, VECTREX) and eight
corrected ones (32X, MD32X, ATOMISWAVE, NAOMI, FDS, PCECD, MAME2003, MAME2010)
that share the wordmark sources above. SCUMMVM adapts the ScummVM logo,
Copyright (c) 2004, 2009 Jean Marc Gimenez (`originals/scummvm_logo.svg` in
https://github.com/scummvm/scummvm-media, revision
`3685fcd62e09277e114eb0ef99091a9c55335f00`), under its CC BY-SA 3.0 branding
license; the card is also CC BY-SA 3.0. EASYRPG adapts the EasyRPG Team's
official logo, CC BY-SA 4.0, and the card is also CC BY-SA 4.0. PICO8 is
original UMRK lettering, CC0 1.0; PICO-8 is Lexaloffle's name. The other 26
system cards and `_apps.png` (the Leaf mark) have no per-file source note yet.

**RetroArch menu assets** - RetroArch resolves every icon and font its menu
drivers draw under a single assets directory. Leaf assembles that tree directly
from https://github.com/libretro/retroarch-assets at a pinned commit, pruned to
the subtrees our binary actually reads (`ozone/`, `xmb/monochrome/`, and the
`pkg/` fallback fonts). The artwork is covered by that repository's own
`COPYING`, Creative Commons Attribution 4.0 International; the fonts carry
their own separate licenses, listed above and read from each font's name table
rather than assumed. Per-file provenance - upstream commit, source path,
SHA-256 and license classification for all 929 files - ships in the bundle
itself as `platforms/mlp1/assets/manifest.json`, with a human-readable summary
in `platforms/mlp1/assets/NOTICE.md`.

**Fonts** used by Leaf's own launcher UI are distributed under the SIL Open
Font License 1.1. The Nerd Fonts glyphs used for on-screen keyboard key icons
are MIT-licensed. The RetroArch fallback fonts above are separate works with
their own terms and are not OFL.
