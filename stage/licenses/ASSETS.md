# Bundled asset licenses

Beyond the emulator cores (see `CORES.md`), Leaf bundles artwork and fonts. Each
is the work of its respective authors and is distributed under its own license.
The same summary is shown on-device under **Menu > Info > Device** and at
https://leaf.game/credits.

| Asset | Author / source | License |
|---|---|---|
| Cover Flow console art (icons in the `Jawaka-Coverflow` theme) | Evan Amos - Vanamo Online Game Museum / Wikimedia Commons | Public Domain |
| Default system icons (libretro Systematic pack) | libretro team and contributors | CC BY-SA 4.0 |
| UI fonts (Space Grotesk, Inter, Rounded M+, Nunito, Baloo 2, Fredoka, Lexend, IBM Plex Sans, Noto Sans, Source Han Sans) | respective type designers | SIL OFL 1.1 |
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
