#!/usr/bin/env python3
"""Generate validated MLP1 RetroArch runtime metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import retroarch_inventory


ARCHIVE_EXTENSIONS = {"zip", "7z", "rar", "gz"}
PLAYLIST_EXTENSIONS = {"m3u", "m3u8"}
KNOWN_DISK_CONTROL_CORES = {
    "flycast",
    "flycast_fast_umrk",
    "genesis_plus_gx",
    "mednafen_pce_fast",
    "np2kai",
    "pcsx_rearmed",
    "puae",
    "puae2021",
    "swanstation",
    "yabasanshiro",
}
DEFER_NAME_MARKERS = {"standalone", "stock", "native", "drastic", "ffplay", "pak"}
BLOCKED_PATTERN_WORDS = {"shit"}
# Reference catalogs may advertise cores that are not part of the MLP1 release
# policy. Keep them out until an artifact or stock-parity entry promotes them.
EXCLUDED_REFERENCE_CORE_IDS = {"flycast2021", "flycast2024"}

# Exact values returned by retro_get_system_info().library_name for the MLP1
# stock-parity artifacts. RetroArch uses this byte-for-byte as the per-core
# Saves/ and States/ directory name. Keep this probe-derived snapshot separate
# from Spruce display/config aliases; --build-report validation is the gate that
# detects a stale value when a core artifact changes.
MLP1_PACKAGED_CORE_LIBRARY_NAMES = {
    "dosbox_pure": "DOSBox-pure",
    "easyrpg": "EasyRPG Player",
    "fake08": "fake-08",
    "fbalpha2012": "FB Alpha 2012",
    "fbneo": "FinalBurn Neo",
    "fceumm": "FCEUmm",
    "flycast": "Flycast",
    "flycast_fast_umrk": "FlyCast Fast UMRK",
    "gambatte": "Gambatte",
    "genesis_plus_gx": "Genesis Plus GX",
    "gpsp": "gpSP",
    "gw": "Game & Watch",
    "handy": "Handy",
    "mame": "MAME",
    "mame2003_plus": "MAME 2003-Plus",
    "mame2010": "MAME 2010",
    "mednafen_ngp": "Beetle NeoPop",
    "mednafen_pce_fast": "Beetle PCE Fast",
    "mednafen_wswan": "Beetle WonderSwan",
    "mgba": "mGBA",
    "mupen64plus_next": "Mupen64Plus-Next",
    "np2kai": "Neko Project II kai",
    "pcsx_rearmed": "PCSX-ReARMed",
    "picodrive": "PicoDrive",
    "prosystem": "ProSystem",
    "puae": "PUAE",
    "puae2021": "PUAE 2021",
    "snes9x": "Snes9x",
    "stella2014": "Stella 2014",
    "swanstation": "SwanStation",
    "yabasanshiro": "YabaSanshiro",
}

# A flat save/state may only be recovered into the core that historically
# owned that system's unsorted namespace. Systems with multiple plausible
# historical owners are intentionally absent.
LEGACY_FLAT_CORE_BY_SYSTEM = {
    "32X": "genesis_plus_gx",
    "ATARI2600": "stella2014",
    "DC": "flycast",
    "DOS": "dosbox_pure",
    "EASYRPG": "easyrpg",
    "FC": "fceumm",
    "FDS": "fceumm",
    "GBA": "mgba",
    "GG": "genesis_plus_gx",
    "GW": "gw",
    "LYNX": "handy",
    "MAME2003": "mame2003_plus",
    "MAME2010": "mame2010",
    "MD": "genesis_plus_gx",
    "MD32X": "genesis_plus_gx",
    "MS": "genesis_plus_gx",
    "N64": "mupen64plus_next",
    "NGP": "mednafen_ngp",
    "NGPC": "mednafen_ngp",
    "PCE": "mednafen_pce_fast",
    "PCECD": "mednafen_pce_fast",
    "PICO8": "fake08",
    "SATURN": "yabasanshiro",
    "SEGACD": "genesis_plus_gx",
    "SEVENTYEIGHTHUNDRED": "prosystem",
    "SFC": "snes9x",
    "WS": "mednafen_wswan",
    "WSC": "mednafen_wswan",
}

FAT32_INVALID_COMPONENT_CHARS = frozenset('<>:"/\\|?*')
SHA256_RE = re.compile(r"[0-9a-f]{64}")
FAT32_RESERVED_COMPONENTS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def config_folder_error(value: Any) -> str | None:
    """Return why a RetroArch library-name folder is not FAT32 portable."""
    if not isinstance(value, str) or not value:
        return "must be a non-empty string"
    if value in {".", ".."}:
        return "must not be a relative path component"
    if value[-1] in {" ", "."}:
        return "must not end in a space or period"
    for char in value:
        codepoint = ord(char)
        if 0xD800 <= codepoint <= 0xDFFF:
            return f"contains invalid Unicode surrogate U+{codepoint:04X}"
        if codepoint < 32 or char in FAT32_INVALID_COMPONENT_CHARS:
            return f"contains invalid character U+{codepoint:04X}"
    if len(value.encode("utf-8")) > 255:
        return "exceeds the 255-byte FAT32 component limit"
    reserved_stem = value.split(".", 1)[0].upper()
    if reserved_stem in FAT32_RESERVED_COMPONENTS:
        return f"uses reserved DOS device name {reserved_stem}"
    return None

SUPPLEMENTAL_CORE_ROWS = [
    {
        "id": "bluemsx",
        "display_name": "blueMSX",
        "type": "retroarch",
        "libretro_name": "bluemsx",
        "file_name": "bluemsx_libretro.so",
        "config_folder": "blueMSX",
        "info_name": "bluemsx_libretro.info",
        "path": None,
        "supports_menu": True,
        "supports_savestate": True,
        "supports_disk_control": False,
        "needs_swap": False,
        "platforms": ["mlp1"],
        "status": "missing",
    },
    {
        "id": "drastic",
        "display_name": "DraStic",
        "type": "path",
        "libretro_name": None,
        "file_name": None,
        "config_folder": None,
        "info_name": None,
        "path": "emulators/drastic/launch.sh",
        "supports_menu": True,
        "supports_savestate": False,
        "supports_disk_control": False,
        "needs_swap": False,
        "platforms": ["mlp1"],
        "status": "packaged",
    },
    {
        # Fun DraStic is the same closed-source drastic64 binary as "drastic"
        # with tenlevels' frontend hooked in over SDL. It is an alternate, not
        # a replacement: DraStic stays the NDS default.
        "id": "fun_drastic",
        "display_name": "Fun DraStic",
        "type": "path",
        "libretro_name": None,
        "file_name": None,
        "config_folder": None,
        "info_name": None,
        "path": "emulators/fun-drastic/launch.sh",
        "supports_menu": True,
        "supports_savestate": False,
        "supports_disk_control": False,
        "needs_swap": False,
        "platforms": ["mlp1"],
        "status": "packaged",
    },
    {
        "id": "flycast_standalone",
        "display_name": "Flycast Standalone",
        "type": "path",
        "libretro_name": None,
        "file_name": None,
        "config_folder": "Flycast Standalone",
        "info_name": None,
        "path": "emulators/flycast/launch.sh",
        "supports_menu": True,
        "supports_savestate": False,
        "supports_disk_control": False,
        "needs_swap": False,
        "requires_direct_drm": True,
        "platforms": ["mlp1"],
        "status": "packaged",
    },
    {
        "id": "mednafen_vb",
        "display_name": "Beetle VB",
        "type": "retroarch",
        "libretro_name": "mednafen_vb",
        "file_name": "mednafen_vb_libretro.so",
        "config_folder": "Beetle VB",
        "info_name": "mednafen_vb_libretro.info",
        "path": None,
        "supports_menu": True,
        "supports_savestate": True,
        "supports_disk_control": False,
        "needs_swap": False,
        "platforms": ["mlp1"],
        "status": "missing",
    },
    {
        "id": "mupen64plus_standalone",
        "display_name": "Mupen64Plus Standalone",
        "type": "path",
        "libretro_name": None,
        "file_name": None,
        "config_folder": "Mupen64Plus Standalone",
        "info_name": None,
        "path": "emulators/mupen64plus/launch.sh",
        "supports_menu": True,
        "supports_savestate": True,
        "supports_disk_control": False,
        "needs_swap": False,
        "platforms": ["mlp1"],
        "status": "packaged",
    },
    {
        "id": "ports",
        "display_name": "Ports",
        "type": "path",
        "libretro_name": None,
        "file_name": None,
        "config_folder": None,
        "info_name": None,
        "path": "emulators/ports/launch.sh",
        "supports_menu": False,
        "supports_savestate": False,
        "supports_disk_control": False,
        "needs_swap": False,
        "platforms": ["mlp1"],
        "status": "packaged",
    },
    {
        "id": "ppsspp",
        "display_name": "PPSSPP (Vulkan)",
        "type": "path",
        "libretro_name": None,
        "file_name": None,
        "config_folder": None,
        "info_name": None,
        "path": "emulators/ppsspp/launch.sh",
        "supports_menu": False,
        "supports_savestate": False,
        "supports_disk_control": False,
        "needs_swap": False,
        "requires_direct_drm": True,
        "platforms": ["mlp1"],
        "status": "packaged",
    },
    {
        "id": "ppsspp_gles",
        "display_name": "PPSSPP (GLES)",
        "type": "path",
        "libretro_name": None,
        "file_name": None,
        "config_folder": None,
        "info_name": None,
        "path": "emulators/ppsspp/launch-gles.sh",
        "supports_menu": False,
        "supports_savestate": False,
        "supports_disk_control": False,
        "needs_swap": False,
        "requires_direct_drm": False,
        "platforms": ["mlp1"],
        "status": "packaged",
    },
    {
        "id": "vecx",
        "display_name": "VecX",
        "type": "retroarch",
        "libretro_name": "vecx",
        "file_name": "vecx_libretro.so",
        "config_folder": "vecx",
        "info_name": "vecx_libretro.info",
        "path": None,
        "supports_menu": True,
        "supports_savestate": True,
        "supports_disk_control": False,
        "needs_swap": False,
        "platforms": ["mlp1"],
        "status": "missing",
    },
    {
        "id": "yabasanshiro_standalone",
        "display_name": "YabaSanshiro Standalone",
        "type": "path",
        "libretro_name": None,
        "file_name": None,
        "config_folder": "YabaSanshiro Standalone",
        "info_name": None,
        "path": "emulators/yabasanshiro/launch.sh",
        "supports_menu": True,
        "supports_savestate": False,
        "supports_disk_control": False,
        "needs_swap": False,
        "requires_direct_drm": True,
        "platforms": ["mlp1"],
        "status": "packaged",
    },
]
CORE_ORDER_AFTER = {"yabasanshiro_standalone": "yabasanshiro"}
SUPPLEMENTAL_SYSTEM_ROWS = [
    {
        "id": "SEGACD",
        "name": "Sega CD",
        "patterns": ["SEGACD", "segacd", "SCD", "scd", "MEGACD", "megacd"],
        "extensions": ["chd", "cue", "iso"],
        "archive_extensions": ["zip", "7z"],
        "archive_inner_extensions": ["bin", "chd", "cue", "iso"],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": ["m3u"],
        "m3u_generation": "manual",
        "default_core": "genesis_plus_gx",
        "alternate_cores": ["picodrive"],
        "rom_root": "Roms/SEGACD",
        "image_root": "Images/SEGACD",
        "bios_notes": ["bios_CD_U.bin (US)", "bios_CD_E.bin (Europe)", "bios_CD_J.bin (Japan)"],
    },
    {
        "id": "NEOGEO",
        "name": "Neo Geo",
        "patterns": ["NEOGEO", "neogeo", "NeoGeo", "NEO_GEO", "ARCADE_NEO", "arcade_neo"],
        "extensions": [],
        "archive_extensions": ["zip", "7z"],
        "archive_inner_extensions": [],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": ["neocd.zip", "neocdz.zip", "neogeo.zip"],
        "playlist_extensions": [],
        "m3u_generation": "none",
        "name_map": True,
        "default_core": "fbneo",
        "alternate_cores": ["fbalpha2012"],
        "rom_root": "Roms/NEOGEO",
        "image_root": "Images/NEOGEO",
        "bios_notes": ["neogeo.zip (required, place in BIOS folder)"],
    },
    {
        "id": "FDS",
        "name": "Famicom Disk",
        "patterns": ["FDS", "fds", "FAMICOMDISK", "famicomdisk"],
        "extensions": ["fds", "nes"],
        "archive_extensions": ["7z", "zip"],
        "archive_inner_extensions": ["fds", "nes"],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": [],
        "m3u_generation": "none",
        "default_core": "fceumm",
        "alternate_cores": ["nestopia"],
        "rom_root": "Roms/FDS",
        "image_root": "Images/FDS",
        "bios_notes": ["disksys.rom (required)"],
    },
    {
        "id": "PCECD",
        "name": "PC Engine CD",
        "patterns": ["PCECD", "pcecd", "PCENGINECD", "pcenginecd", "TURBOGRAFXCD", "turbografxcd"],
        "extensions": ["ccd", "chd", "cue", "img", "iso"],
        "archive_extensions": [],
        "archive_inner_extensions": ["ccd", "chd", "cue", "img", "iso"],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": ["m3u"],
        "m3u_generation": "manual",
        "default_core": "mednafen_pce_fast",
        "alternate_cores": [],
        "rom_root": "Roms/PCECD",
        "image_root": "Images/PCECD",
        "bios_notes": ["syscard3.pce (required)"],
    },
    {
        "id": "SFC_JP",
        "name": "Super Famicom",
        "patterns": ["SFC_JP", "sfc_jp", "SUPERFAMICOM_JP"],
        "extensions": ["bs", "bsx", "dx2", "fig", "gd3", "gd7", "sfc", "smc", "st", "swc"],
        "archive_extensions": ["7z", "zip"],
        "archive_inner_extensions": ["bs", "bsx", "dx2", "fig", "gd3", "gd7", "sfc", "smc", "st", "swc"],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": [],
        "m3u_generation": "none",
        "default_core": "snes9x",
        "alternate_cores": [],
        "rom_root": "Roms/SFC_JP",
        "image_root": "Images/SFC_JP",
        "bios_notes": [],
    },
    {
        "id": "SEVENTYEIGHTHUNDRED",
        "name": "Atari 7800",
        "patterns": ["SEVENTYEIGHTHUNDRED", "seventyeighthundred", "ATARI7800", "atari7800", "A7800", "a7800"],
        "extensions": ["a78", "bin"],
        "archive_extensions": ["7z", "zip"],
        "archive_inner_extensions": ["a78", "bin"],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": [],
        "m3u_generation": "none",
        "default_core": "prosystem",
        "alternate_cores": [],
        "rom_root": "Roms/SEVENTYEIGHTHUNDRED",
        "image_root": "Images/SEVENTYEIGHTHUNDRED",
        "bios_notes": [],
    },
    {
        "id": "NDS",
        "name": "Nintendo DS",
        "patterns": ["NDS", "nds", "NINTENDODS", "nintendods"],
        "extensions": ["nds"],
        "archive_extensions": ["7z", "zip"],
        "archive_inner_extensions": ["nds"],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": [],
        "m3u_generation": "none",
        "default_core": "drastic",
        "alternate_cores": ["fun_drastic"],
        "rom_root": "Roms/NDS",
        "image_root": "Images/NDS",
        "bios_notes": [
            "Both Nintendo DS emulators bundle DraStic's own free replacement "
            "BIOS, so no BIOS file of your own is needed to play.",
            "A few games refuse to start without the original Nintendo BIOS, "
            "and the DS firmware settings need the firmware dump. Put "
            "nds_bios_arm7.bin (16 KB), nds_bios_arm9.bin (4 KB) and "
            "nds_firmware.bin in BIOS/NDS.",
        ],
    },
    {
        "id": "PSP",
        "name": "PSP",
        "patterns": ["PSP", "psp", "PLAYSTATIONPORTABLE", "playstationportable"],
        "extensions": ["chd", "cso", "iso", "pbp"],
        "archive_extensions": [],
        "archive_inner_extensions": ["chd", "cso", "iso", "pbp"],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": [],
        "m3u_generation": "none",
        "default_core": "ppsspp",
        "alternate_cores": ["ppsspp_gles"],
        "rom_root": "Roms/PSP",
        "image_root": "Images/PSP",
        "bios_notes": [],
    },
    {
        "id": "PORTS",
        "name": "Ports",
        "patterns": ["PORTS", "ports"],
        "extensions": ["sh"],
        "archive_extensions": [],
        "archive_inner_extensions": [],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": [],
        "m3u_generation": "none",
        "default_core": "ports",
        "alternate_cores": [],
        "rom_root": "Roms/PORTS",
        "image_root": "Images/PORTS",
        "bios_notes": [],
    },
    {
        "id": "COLECO",
        "name": "ColecoVision",
        "patterns": ["COLECO", "coleco", "COLECOVISION", "colecovision"],
        "extensions": ["bin", "col", "rom"],
        "archive_extensions": ["7z", "zip"],
        "archive_inner_extensions": ["bin", "col", "rom"],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": [],
        "m3u_generation": "none",
        "default_core": "bluemsx",
        "alternate_cores": [],
        "rom_root": "Roms/COLECO",
        "image_root": "Images/COLECO",
        "bios_notes": [],
    },
    {
        "id": "VECTREX",
        "name": "Vectrex",
        "patterns": ["VECTREX", "vectrex"],
        "extensions": ["bin", "vec"],
        "archive_extensions": ["7z", "zip"],
        "archive_inner_extensions": ["bin", "vec"],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": [],
        "m3u_generation": "none",
        "default_core": "vecx",
        "alternate_cores": [],
        "rom_root": "Roms/VECTREX",
        "image_root": "Images/VECTREX",
        "bios_notes": [],
    },
    {
        "id": "DOS",
        "name": "MS-DOS",
        "patterns": ["DOS", "dos", "MSDOS", "msdos", "DOSBOX", "dosbox"],
        "extensions": ["bat", "com", "conf", "dosz", "exe", "ima", "img", "ins", "iso", "jrc", "tc", "vhd"],
        "archive_extensions": ["zip"],
        "archive_inner_extensions": ["bat", "com", "conf", "dosz", "exe", "ima", "img", "ins", "iso", "jrc", "tc", "vhd"],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": ["m3u", "m3u8"],
        "m3u_generation": "none",
        "default_core": "dosbox_pure",
        "alternate_cores": [],
        "rom_root": "Roms/DOS",
        "image_root": "Images/DOS",
        "bios_notes": [],
    },
    {
        "id": "EASYRPG",
        "name": "EasyRPG",
        "patterns": ["EASYRPG", "easyrpg", "RPGMAKER", "rpgmaker"],
        "extensions": ["easyrpg", "ldb"],
        "archive_extensions": ["zip"],
        "archive_inner_extensions": ["easyrpg", "ldb"],
        "archive_mode": "pass_through",
        "file_names": ["RPG_RT.ldb"],
        "ignore_file_names": [],
        "playlist_extensions": [],
        "m3u_generation": "none",
        "default_core": "easyrpg",
        "alternate_cores": [],
        "rom_root": "Roms/EASYRPG",
        "image_root": "Images/EASYRPG",
        "bios_notes": [],
    },
    {
        "id": "GW",
        "name": "Game & Watch",
        "patterns": ["GW", "gw", "GAMEANDWATCH", "gameandwatch"],
        "extensions": ["mgw"],
        "archive_extensions": ["7z", "zip"],
        "archive_inner_extensions": ["mgw"],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": [],
        "m3u_generation": "none",
        "default_core": "gw",
        "alternate_cores": [],
        "rom_root": "Roms/GW",
        "image_root": "Images/GW",
        "bios_notes": [],
    },
    {
        "id": "PICO8",
        "name": "Pico-8",
        "patterns": ["PICO8", "pico8", "PICO", "pico", "P8", "p8", "FAKE08", "fake08"],
        "extensions": ["p8", "png"],
        "archive_extensions": [],
        "archive_inner_extensions": ["p8", "png"],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": [],
        "m3u_generation": "none",
        "default_core": "fake08",
        "alternate_cores": [],
        "rom_root": "Roms/PICO8",
        "image_root": "Images/PICO8",
        "bios_notes": [],
    },
    {
        "id": "VB",
        "name": "Virtual Boy",
        "patterns": ["VB", "vb", "VIRTUALBOY", "virtualboy"],
        "extensions": ["vb", "vboy"],
        "archive_extensions": ["7z", "zip"],
        "archive_inner_extensions": ["vb", "vboy"],
        "archive_mode": "pass_through",
        "file_names": [],
        "ignore_file_names": [],
        "playlist_extensions": [],
        "m3u_generation": "none",
        "default_core": "mednafen_vb",
        "alternate_cores": [],
        "rom_root": "Roms/VB",
        "image_root": "Images/VB",
        "bios_notes": [],
    },
]
SUPPLEMENTAL_SYSTEM_IDS = {row["id"] for row in SUPPLEMENTAL_SYSTEM_ROWS}
SYSTEM_METADATA_ALIASES = {
    "TG16": "PCE",
}
SYSTEM_NAME_OVERRIDES = {
    "AMIGA": "Amiga",
    "NAOMI": "Sega Naomi",
    "PC98": "NEC PC-98",
    "TG16": "TurboGrafx-16",
}
# These are reviewed public-folder aliases, not a mirror of every upstream
# nickname. Current Allium aliases span separate UMRK libraries and can also
# drift independently, so new aliases require an explicit catalog change.
SYSTEM_PATTERN_OVERRIDES = {
    "AMIGA": ["AMIGA", "Amiga", "amiga", "amiga500", "amiga1200"],
    "ARCADE": ["ARCADE", "Arcade", "arcade"],
    "MD": ["MD", "GENESIS", "md", "MEGADRIVE", "megadrive", "GEN"],
    "MAME": ["MAME", "mame", "MAME2003PLUS", "mame2003plus"],
    "MS": ["MS", "MASTERSYSTEM", "ms", "SMS", "sms"],
    "NGP": ["NGP", "NEOGEOPOCKET", "neogeopocket", "NGC", "ngp"],
    "NGPC": ["NGPC", "NEOGEOPOCKETCOLOR", "neogeopocketcolor", "ngpc"],
    "PCE": [
        "PCE",
        "pce",
        "PCENGINE",
        "pcengine",
        "TURBOGRAFX",
        "turbografx",
        "TURBOGRAFX16",
        "turbografx16",
        "TG16",
    ],
    "PC98": ["PC98", "pc98", "necpc98", "NECPC98"],
    "SFC": [
        "SFC",
        "sfc",
        "SNES",
        "snes",
        "SUPERFAMICOM",
        "superfamicom",
        "SUPERNES",
        "supernes",
        "SFC_JP",
        "sfc_jp",
        "SUPERFAMICOM_JP",
        "SUPA",
    ],
    "WS": ["WS", "WONDERSWAN", "wonderswan", "ws"],
    "WSC": [
        "WSC",
        "WONDERSWANC",
        "wonderswanc",
        "WONDERSWANCOLOR",
        "wonderswancolor",
        "wsc",
    ],
}
# Upstream aliases deliberately excluded from the public catalog. Keeping this
# separate from the accepted aliases makes a newly added upstream nickname a
# generation error instead of silently dropping it behind an override.
IGNORED_SYSTEM_PATTERNS = {
    "AMIGA": ["amiga600", "amigacd32", "cdtv"],
    "ARCADE": ["fba", "fbneo", "mame"],
    "MD": ["genesis", "megadrivejp"],
    "MAME": ["ARCADE", "arcade", "fba", "fbneo"],
    "MS": ["mark3", "mastersystem"],
    "NGP": ["ngpc"],
    "NGPC": ["NGC", "NGP"],
    "PCE": ["tg16"],
    "PC98": ["NINETYEIGHT", "PCNINETYEIGHT"],
    "SFC": ["snesna"],
    "WS": ["wonderswancolor"],
    "WSC": [],
}
SYSTEM_BIOS_NOTES = {
    "AMIGA": [
        "puae/Kickstart ROMs and rom.key when required "
        "(user-supplied, place under BIOS)"
    ],
    "ATOMISWAVE": ["dc/awbios.zip (user-supplied, place under BIOS)"],
    "DC": [
        "dc/dc_boot.bin (optional/recommended, user-supplied, place under BIOS)"
    ],
    "NAOMI": [
        "dc/naomi.zip for Naomi and Naomi GD-ROM (user-supplied, place under BIOS)",
        "dc/naomi2.zip for Naomi 2 (user-supplied, place under BIOS)",
        "dc/airlbios.zip, dc/f355bios.zip, dc/f355dlx.zip, or dc/hod2bios.zip when required by a game",
    ],
    "PC98": [
        "np2kai/font.bmp or np2kai/FONT.ROM (needed for text, place under BIOS)"
    ],
}
ADDITIONAL_SYSTEM_MAPPINGS = {
    "AMIGA": "puae",
    "ATOMISWAVE": "flycast_standalone",
    "NAOMI": "flycast_standalone",
    "PC98": "np2kai",
}
NAME_MAP_SYSTEM_IDS = {
    "ARCADE",
    "ATOMISWAVE",
    "MAME",
    "MAME2003",
    "MAME2010",
    "NAOMI",
    "NEOGEO",
}
SYSTEM_CORE_OVERRIDES = {
    "32X": {
        "default_core": "picodrive",
        "alternate_cores": [],
    },
    "AMIGA": {
        "default_core": "puae2021",
        "alternate_cores": ["puae"],
    },
    "DC": {
        "default_core": "flycast_standalone",
        "alternate_cores": [
            "flycast",
            "flycast_fast_umrk",
            "km_flycast_xtreme",
        ],
    },
    "ATOMISWAVE": {
        "default_core": "flycast_standalone",
        "alternate_cores": [
            "flycast",
            "flycast_fast_umrk",
            "km_flycast_xtreme",
        ],
    },
    "NAOMI": {
        "default_core": "flycast_standalone",
        "alternate_cores": [
            "flycast",
            "flycast_fast_umrk",
            "km_flycast_xtreme",
        ],
    },
    "PC98": {
        "default_core": "np2kai",
        "alternate_cores": [],
    },
    "MAME": {
        "default_core": "mame",
        "alternate_cores": ["mame2003_plus"],
    },
    "N64": {
        "default_core": "mupen64plus_standalone",
        "alternate_cores": [
            "mupen64plus_next",
            "km_ludicrousn64_2k22_xtreme_amped",
            "parallel_n64",
            "km_parallel_n64_xtreme_amped_turbo",
            "mupen64plus",
        ],
    },
    "MD32X": {
        "default_core": "picodrive",
        "alternate_cores": [],
    },
    "SATURN": {
        "default_core": "yabasanshiro",
        "alternate_cores": [
            "yabasanshiro_standalone",
            "yabasanshiro_a133p",
            "yabasanshiro_smartpros",
        ],
    },
}

SYSTEM_CONTENT_OVERRIDES = {
    "AMIGA": {
        "extensions": [
            "adf",
            "adz",
            "ccd",
            "chd",
            "cue",
            "dms",
            "fdi",
            "hdf",
            "hdz",
            "iso",
            "lha",
            "mds",
            "nrg",
            "raw",
            "rp9",
            "uae",
        ],
        "archive_extensions": ["7z", "zip"],
        "archive_inner_extensions": [
            "adf",
            "adz",
            "ccd",
            "chd",
            "cue",
            "dms",
            "fdi",
            "hdf",
            "hdz",
            "iso",
            "lha",
            "mds",
            "nrg",
            "raw",
            "rp9",
            "uae",
        ],
        "archive_mode": "pass_through",
        "playlist_extensions": ["m3u"],
        "m3u_generation": "manual",
    },
}


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def leaf_repo_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_build_report_artifact(
    build_report_path: Path, subdirectory: str, file_name: str
) -> Path | None:
    """Find an artifact in either supported Cores-spruce report layout."""
    for candidate in (
        build_report_path.parent / subdirectory / file_name,
        build_report_path.parent / file_name,
    ):
        if candidate.is_file():
            return candidate
    return None


def validate_build_report_contract(
    build_report_path: Path, cores: dict[str, Any]
) -> list[str]:
    """Validate the complete probed MLP1 report before metadata is written."""
    errors: list[str] = []
    try:
        report = json.loads(build_report_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"build report missing: {build_report_path}"]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"build report unreadable: {build_report_path}: {exc}"]
    if not isinstance(report, dict):
        return [f"build report root must be an object: {build_report_path}"]

    if report.get("version") != 2:
        errors.append(f"build report version must be 2, got {report.get('version')!r}")
    if report.get("platform") != "mlp1":
        errors.append(
            f"build report platform must be 'mlp1', got {report.get('platform')!r}"
        )
    if report.get("status") != "passed":
        errors.append(f"build report status must be 'passed', got {report.get('status')!r}")
    if report.get("library_name_status") != "complete":
        errors.append(
            "build report library_name_status must be 'complete', got "
            f"{report.get('library_name_status')!r}"
        )

    expected_rows = [
        row
        for row in cores.get("cores", [])
        if isinstance(row, dict)
        and row.get("type") == "retroarch"
        and row.get("status") == "packaged"
    ]
    expected_by_id = {row.get("id"): row for row in expected_rows if row.get("id")}
    expected_ids = set(expected_by_id)

    report_rows = report.get("cores")
    if not isinstance(report_rows, list):
        errors.append("build report cores must be a list")
        return errors

    statuses = [
        row.get("status") if isinstance(row, dict) else None for row in report_rows
    ]
    actual_counts = {
        "requested_count": len(report_rows),
        "built_count": statuses.count("built"),
        "failed_count": statuses.count("failed"),
        "deferred_count": statuses.count("deferred"),
        "library_name_count": sum(
            1
            for row in report_rows
            if isinstance(row, dict)
            and row.get("status") == "built"
            and isinstance(row.get("library_name"), str)
            and bool(row.get("library_name"))
        ),
    }
    for field, actual in actual_counts.items():
        if report.get(field) != actual:
            errors.append(
                f"build report {field} does not match rows: "
                f"{report.get(field)!r} != {actual}"
            )

    expected_count = len(expected_rows)
    for field in ("requested_count", "built_count", "library_name_count"):
        if report.get(field) != expected_count:
            errors.append(
                f"full build report {field} must equal packaged core count: "
                f"{report.get(field)!r} != {expected_count}"
            )
    for field in ("failed_count", "deferred_count"):
        if report.get(field) != 0:
            errors.append(f"full build report {field} must be 0, got {report.get(field)!r}")

    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    for index, row in enumerate(report_rows):
        if not isinstance(row, dict):
            errors.append(f"build report core row {index} must be an object")
            continue

        core_id = row.get("core")
        core_file = row.get("core_file")
        if not isinstance(core_id, str) or not core_id:
            errors.append(f"build report core row {index} has invalid core id: {core_id!r}")
            continue
        if core_id in seen_ids:
            errors.append(f"build report duplicate core id: {core_id}")
        seen_ids.add(core_id)
        if isinstance(core_file, str) and core_file:
            if core_file in seen_files:
                errors.append(f"build report duplicate core_file: {core_file}")
            seen_files.add(core_file)

        expected = expected_by_id.get(core_id)
        if expected is None:
            errors.append(f"build report contains unexpected core: {core_id}")
            continue
        if row.get("status") != "built":
            errors.append(
                f"build report packaged core must be built: {core_id}: "
                f"{row.get('status')!r}"
            )

        exact_fields = {
            "core_file": expected.get("file_name"),
            "info_file": expected.get("info_name"),
            "library_name": expected.get("config_folder"),
        }
        for field, expected_value in exact_fields.items():
            if row.get(field) != expected_value:
                errors.append(
                    f"build report {core_id} {field} mismatch: "
                    f"report={row.get(field)!r} metadata={expected_value!r}"
                )

        expected_sha256 = row.get("sha256")
        if not isinstance(expected_sha256, str) or not SHA256_RE.fullmatch(expected_sha256):
            errors.append(f"build report {core_id} has invalid sha256: {expected_sha256!r}")
        artifact_file = expected.get("file_name")
        artifact_path = (
            find_build_report_artifact(build_report_path, "cores", artifact_file)
            if isinstance(artifact_file, str) and artifact_file
            else None
        )
        if artifact_path is None:
            errors.append(f"build report core artifact missing: {artifact_file}")
        elif isinstance(expected_sha256, str) and SHA256_RE.fullmatch(expected_sha256):
            actual_sha256 = sha256_file(artifact_path)
            if actual_sha256 != expected_sha256:
                errors.append(
                    f"build report checksum mismatch: {artifact_file}: "
                    f"report={expected_sha256} actual={actual_sha256}"
                )

        info_file = expected.get("info_name")
        info_path = (
            find_build_report_artifact(build_report_path, "info", info_file)
            if isinstance(info_file, str) and info_file
            else None
        )
        if info_path is None:
            errors.append(f"build report info artifact missing: {info_file}")

    for core_id in sorted(expected_ids - seen_ids):
        errors.append(f"full build report missing packaged core: {core_id}")

    return errors


def unique_sorted(values: list[str] | set[str]) -> list[str]:
    # Tie-break casefold-equal values byte-wise so output is deterministic
    # across runs (set iteration order is hash-randomized).
    return sorted({value for value in values if value}, key=lambda item: (item.casefold(), item))


def unique_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def core_id_from_file(file_name: str) -> str:
    return retroarch_inventory.core_id_from_filename(file_name) or Path(file_name).stem


def core_file_from_id(core_id: str) -> str:
    return f"{core_id}_libretro.so"


def info_file_from_id(core_id: str) -> str:
    return f"{core_id}_libretro.info"


def clean_core_name(name: str | None) -> str | None:
    if not name:
        return None
    value = Path(str(name)).name.strip()
    if not value:
        return None
    value = value.removesuffix(".so")
    value = value.removesuffix("_libretro")
    value = value.removesuffix("-libretro")
    value = value.lower().replace("-", "_")
    value = re.sub(r"[^a-z0-9_]+", "_", value).strip("_")
    if not value:
        return None
    if any(marker in value for marker in DEFER_NAME_MARKERS):
        return None
    return value


def humanize_core_id(core_id: str) -> str:
    special = {
        "2048": "2048",
        "fbneo": "FinalBurn Neo",
        "fceumm": "FCEUmm",
        "flycast_fast_umrk": "FlyCast Fast UMRK",
        "mgba": "mGBA",
        "mupen64plus_next": "Mupen64Plus Next",
        "pcsx_rearmed": "PCSX-ReARMed",
        "snes9x": "Snes9x",
    }
    if core_id in special:
        return special[core_id]
    return " ".join(part.upper() if part in {"gba", "pce", "ngp", "wswan"} else part.capitalize() for part in core_id.split("_"))


def resolve_spruce_folder(value: str | None, core_id: str) -> str:
    if not value or value == "UNKNOWN":
        return humanize_core_id(core_id)
    return value.replace("$(arch_suffix)", "64")


def parse_stock_parity_cores(build_script: Path) -> list[str]:
    text = build_script.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"STOCK_PARITY_CORES=\(\n(?P<body>.*?)\n\)", text, re.S)
    if not match:
        return []
    cores: list[str] = []
    for line in match.group("body").splitlines():
        value = line.strip().split("#", 1)[0].strip().strip('"').strip("'")
        if value:
            cores.append(value)
    return cores


def allium_core_lookup(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {core["id"]: core for core in inventory["allium"].get("cores", [])}


def current_default_core_ids(inventory: dict[str, Any]) -> set[str]:
    return {
        mapping["core_id"]
        for mapping in system_mappings(inventory)
        if mapping.get("core_id")
    }


def system_mappings(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    """Return current catalog mappings plus the small set of new supported systems."""
    by_id = {
        system_id: {"system_id": system_id, "core_id": core_id}
        for system_id, core_id in ADDITIONAL_SYSTEM_MAPPINGS.items()
    }
    by_id.update(
        {
            mapping["system_id"]: mapping
            for mapping in inventory["umrk"].get("current_mappings", [])
            if mapping.get("system_id")
        }
    )
    return [by_id[system_id] for system_id in sorted(by_id)]


def reference_core_ids_for_current_systems(inventory: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for mapping in system_mappings(inventory):
        system_id = mapping["system_id"]
        if system_id in SUPPLEMENTAL_SYSTEM_IDS:
            continue
        if system_id in ADDITIONAL_SYSTEM_MAPPINGS:
            override = SYSTEM_CORE_OVERRIDES[system_id]
            result.add(override["default_core"])
            result.update(override["alternate_cores"])
            continue
        metadata_id = SYSTEM_METADATA_ALIASES.get(system_id, system_id)
        allium_console = retroarch_inventory.find_allium_console(inventory["allium"], metadata_id)
        spruce_system = retroarch_inventory.find_spruce_system(inventory["spruce"], metadata_id)
        if allium_console:
            result.update(filter(None, (clean_core_name(core) for core in allium_console.get("cores", []))))
        if spruce_system:
            result.add(clean_core_name(spruce_system.get("default_emulator")) or "")
            for selected in spruce_system.get("selected_emulators", []):
                result.add(clean_core_name(selected) or "")
            for option_group in spruce_system.get("emulator_options", []):
                for option in option_group.get("options", []):
                    result.add(clean_core_name(option) or "")
    result.discard("")
    result.difference_update(EXCLUDED_REFERENCE_CORE_IDS)
    return result


def build_core_catalog(inventory: dict[str, Any], stock_core_ids: list[str]) -> dict[str, Any]:
    core_files = set(inventory["umrk"].get("core_files", []))
    info_files = set(inventory["umrk"].get("info_files", []))
    spruce_mappings = inventory["spruce"].get("core_mappings", {})
    allium_cores = allium_core_lookup(inventory)

    core_ids = set(stock_core_ids)
    core_ids.update(core_id_from_file(file_name) for file_name in core_files)
    core_ids.update(current_default_core_ids(inventory))
    core_ids.update(reference_core_ids_for_current_systems(inventory))

    rows: list[dict[str, Any]] = []
    for core_id in sorted(core_ids):
        file_name = core_file_from_id(core_id)
        info_name = info_file_from_id(core_id)
        allium_core = allium_cores.get(core_id, {})
        is_packaged = file_name in core_files and info_name in info_files
        core_type = "retroarch"
        path = None

        if allium_core.get("type") == "path":
            core_type = "path"
            path = allium_core.get("path")
            file_name = None
            info_name = None

        rows.append(
            {
                "id": core_id,
                "display_name": allium_core.get("name") or resolve_spruce_folder(spruce_mappings.get(file_name or ""), core_id),
                "type": core_type,
                "libretro_name": core_id if core_type == "retroarch" else None,
                "file_name": file_name,
                "config_folder": (
                    MLP1_PACKAGED_CORE_LIBRARY_NAMES.get(core_id)
                    if core_type == "retroarch" and is_packaged
                    else resolve_spruce_folder(spruce_mappings.get(file_name or ""), core_id)
                    if core_type == "retroarch"
                    else None
                ),
                "info_name": info_name,
                "path": path,
                "supports_menu": core_type == "retroarch",
                "supports_savestate": True,
                "supports_disk_control": core_id in KNOWN_DISK_CONTROL_CORES,
                "needs_swap": bool(allium_core.get("swap", False)),
                "requires_direct_drm": False,
                "platforms": ["mlp1"],
                "status": "packaged" if is_packaged else "missing",
            }
        )

    rows_by_id = {row["id"]: row for row in rows}
    for row in SUPPLEMENTAL_CORE_ROWS:
        rows_by_id[row["id"]] = dict(row)
    for row in rows_by_id.values():
        row.setdefault("requires_direct_drm", False)
    core_ids = sorted(rows_by_id)
    for core_id, predecessor in CORE_ORDER_AFTER.items():
        core_ids.remove(core_id)
        core_ids.insert(core_ids.index(predecessor) + 1, core_id)
    rows = [rows_by_id[core_id] for core_id in core_ids]

    return {
        "version": 2,
        "platform": "mlp1",
        "cores": rows,
    }


def source_system_patterns(
    system_id: str,
    allium_console: dict[str, Any] | None,
    spruce_system: dict[str, Any] | None,
) -> list[str]:
    values = [system_id]
    if allium_console:
        values.extend(str(value) for value in allium_console.get("patterns", []))
    if spruce_system:
        values.append(str(spruce_system.get("id", "")))
        values.extend(str(value) for value in spruce_system.get("alternative_folder_names", []))
    return unique_ordered(
        [system_id]
        + unique_sorted(
            [
                value
                for value in values
                if not (set(value.lower().split()) & BLOCKED_PATTERN_WORDS)
            ]
        )
    )


def system_patterns(system_id: str, allium_console: dict[str, Any] | None, spruce_system: dict[str, Any] | None) -> list[str]:
    if system_id in SYSTEM_PATTERN_OVERRIDES:
        return list(SYSTEM_PATTERN_OVERRIDES[system_id])
    return source_system_patterns(system_id, allium_console, spruce_system)


def split_system_extensions(allium_console: dict[str, Any] | None, spruce_system: dict[str, Any] | None) -> tuple[list[str], list[str], list[str]]:
    raw: set[str] = set()
    if allium_console:
        raw.update(str(ext).lower().lstrip(".") for ext in allium_console.get("extensions", []))
    if spruce_system:
        raw.update(str(ext).lower().lstrip(".") for ext in spruce_system.get("extensions", []))
    raw.discard("")

    archive_extensions = sorted(raw & ARCHIVE_EXTENSIONS)
    playlist_extensions = sorted(raw & PLAYLIST_EXTENSIONS)
    extensions = sorted(raw - ARCHIVE_EXTENSIONS - PLAYLIST_EXTENSIONS)
    return extensions, archive_extensions, playlist_extensions


def reference_alternate_cores(
    default_core: str,
    allium_console: dict[str, Any] | None,
    spruce_system: dict[str, Any] | None,
    known_core_ids: set[str],
) -> list[str]:
    candidates: list[str] = []
    if allium_console:
        candidates.extend(clean_core_name(core) or "" for core in allium_console.get("cores", []))
    if spruce_system:
        candidates.append(clean_core_name(spruce_system.get("default_emulator")) or "")
        candidates.extend(clean_core_name(core) or "" for core in spruce_system.get("selected_emulators", []))
        for option_group in spruce_system.get("emulator_options", []):
            candidates.extend(clean_core_name(option) or "" for option in option_group.get("options", []))

    return [
        core
        for core in unique_ordered(candidates)
        if core and core != default_core and core in known_core_ids
    ]


def load_system_folder_policy() -> dict[str, Any]:
    """Canonical user-folder policy (travels with the scripts dir, not --umrk-root)."""
    path = leaf_repo_from_script() / "scripts/system_folder_policy.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing canonical system folder policy: {path}")
    return load_json(path)


# Row fields that are unions of two folded systems. Extension/name fields stay
# sorted; ordered fields preserve canonical-first insertion order.
_FOLD_SORTED_FIELDS = ("extensions", "archive_extensions", "archive_inner_extensions", "playlist_extensions")
_FOLD_NAME_FIELDS = ("file_names", "ignore_file_names")


def merge_folded_row(canonical: dict[str, Any], folded: dict[str, Any]) -> None:
    """Union a folded system's metadata into its canonical survivor row."""
    for field in _FOLD_SORTED_FIELDS:
        canonical[field] = sorted(set(canonical.get(field, [])) | set(folded.get(field, [])))
    for field in _FOLD_NAME_FIELDS:
        canonical[field] = unique_sorted(list(canonical.get(field, [])) + list(folded.get(field, [])))
    canonical["patterns"] = unique_ordered(list(canonical.get("patterns", [])) + list(folded.get("patterns", [])))
    canonical["bios_notes"] = unique_ordered(list(canonical.get("bios_notes", [])) + list(folded.get("bios_notes", [])))

    alternates = list(canonical.get("alternate_cores", [])) + list(folded.get("alternate_cores", []))
    folded_default = folded.get("default_core")
    if folded_default:
        alternates.append(folded_default)
    canonical_default = canonical.get("default_core")
    canonical["alternate_cores"] = [
        core for core in unique_ordered(alternates) if core and core != canonical_default
    ]


def apply_folder_policy(rows_by_id: dict[str, dict[str, Any]], policy: dict[str, Any]) -> None:
    """Collapse duplicate folders into one public folder per user library.

    Internal catalog ids are preserved; only rom_root/image_root and the merged
    patterns change. Fold rows are absorbed and dropped. Policy aliases are added
    unconditionally so folder matching survives even after fold rows disappear on
    a subsequent regeneration (idempotent)."""
    for entry in policy.get("systems", []):
        canonical = rows_by_id.get(entry["canonical_id"])
        if canonical is None:
            # Surfaced by validate_generated; skip best-effort here.
            continue
        for fold_id in entry.get("fold_ids", []):
            folded = rows_by_id.pop(fold_id, None)
            if folded is not None:
                merge_folded_row(canonical, folded)
        public_folder = entry["public_folder"]
        canonical["rom_root"] = f"Roms/{public_folder}"
        canonical["image_root"] = f"Images/{public_folder}"
        if entry.get("display_name"):
            canonical["name"] = entry["display_name"]
        canonical["patterns"] = unique_ordered(
            list(canonical.get("patterns", [])) + list(entry.get("aliases", [])) + [public_folder]
        )


def build_system_catalog(
    inventory: dict[str, Any], core_catalog: dict[str, Any], policy: dict[str, Any] | None = None
) -> dict[str, Any]:
    known_core_ids = {core["id"] for core in core_catalog["cores"]}
    rows: list[dict[str, Any]] = []

    for mapping in system_mappings(inventory):
        system_id = mapping["system_id"]
        metadata_id = SYSTEM_METADATA_ALIASES.get(system_id, system_id)
        default_core = mapping["core_id"]
        allium_console = retroarch_inventory.find_allium_console(inventory["allium"], metadata_id)
        spruce_system = retroarch_inventory.find_spruce_system(inventory["spruce"], metadata_id)
        extensions, archive_extensions, playlist_extensions = split_system_extensions(allium_console, spruce_system)
        ignore_names = spruce_system.get("ignore_file_names", []) if spruce_system else []
        file_names = allium_console.get("file_names", []) if allium_console else []
        m3u_generators = spruce_system.get("m3u_generators", []) if spruce_system else []
        if m3u_generators and "m3u" not in playlist_extensions:
            playlist_extensions = sorted([*playlist_extensions, "m3u"])

        row = {
            "id": system_id,
            "name": (
                SYSTEM_NAME_OVERRIDES.get(system_id)
                or (spruce_system or {}).get("label")
                or (allium_console or {}).get("name")
                or system_id
            ),
            "patterns": system_patterns(system_id, allium_console, spruce_system),
            "extensions": extensions,
            "archive_extensions": archive_extensions,
            "archive_inner_extensions": extensions,
            "archive_mode": "pass_through",
            "file_names": unique_sorted([str(name) for name in file_names]),
            "ignore_file_names": unique_sorted([str(name).lower() for name in ignore_names]),
            "playlist_extensions": playlist_extensions,
            "m3u_generation": "manual" if m3u_generators else "none",
            **({"name_map": True} if system_id in NAME_MAP_SYSTEM_IDS else {}),
            "default_core": default_core,
            "alternate_cores": reference_alternate_cores(
                default_core, allium_console, spruce_system, known_core_ids
            ),
            "rom_root": f"Roms/{system_id}",
            "image_root": f"Images/{system_id}",
            "bios_notes": list(SYSTEM_BIOS_NOTES.get(system_id, [])),
        }
        row.update(SYSTEM_CONTENT_OVERRIDES.get(system_id, {}))
        rows.append(row)

    rows_by_id = {row["id"]: row for row in rows}
    for row in SUPPLEMENTAL_SYSTEM_ROWS:
        rows_by_id[row["id"]] = dict(row)
    for system_id, override in SYSTEM_CORE_OVERRIDES.items():
        row = rows_by_id.get(system_id)
        if row is None:
            continue
        row["default_core"] = override["default_core"]
        row["alternate_cores"] = [
            core
            for core in override["alternate_cores"]
            if core in known_core_ids
            if core != row["default_core"]
        ]
    if policy:
        apply_folder_policy(rows_by_id, policy)
    for system_id, legacy_flat_core in LEGACY_FLAT_CORE_BY_SYSTEM.items():
        row = rows_by_id.get(system_id)
        if row is not None:
            row["legacy_flat_core"] = legacy_flat_core
    rows = [rows_by_id[system_id] for system_id in sorted(rows_by_id)]

    return {
        "version": 2,
        "platform": "mlp1",
        "systems": rows,
    }


def validate_generated(
    cores: dict[str, Any], systems: dict[str, Any], policy: dict[str, Any] | None = None
) -> list[str]:
    errors: list[str] = []
    core_ids: set[str] = set()
    core_by_id: dict[str, dict[str, Any]] = {}
    packaged_config_folders: dict[str, tuple[str, str]] = {}

    if cores.get("version") != 2:
        errors.append(f"cores catalog version must be 2, got {cores.get('version')}")
    if systems.get("version") != 2:
        errors.append(f"systems catalog version must be 2, got {systems.get('version')}")

    for core in cores.get("cores", []):
        core_id = core.get("id")
        if not core_id:
            errors.append("core has no id")
            continue
        if core_id in core_ids:
            errors.append(f"duplicate core id: {core_id}")
        core_ids.add(core_id)
        core_by_id[core_id] = core
        if core.get("type") == "retroarch":
            file_name = core.get("file_name")
            info_name = core.get("info_name")
            if not file_name or not str(file_name).endswith("_libretro.so"):
                errors.append(f"{core_id}: invalid file_name: {file_name}")
            if not info_name or not str(info_name).endswith("_libretro.info"):
                errors.append(f"{core_id}: invalid info_name: {info_name}")
            config_folder = core.get("config_folder")
            if not config_folder:
                errors.append(f"{core_id}: missing config_folder")
            elif core.get("status") == "packaged":
                folder_error = config_folder_error(config_folder)
                if folder_error:
                    errors.append(f"{core_id}: invalid config_folder {config_folder!r}: {folder_error}")
                prior = packaged_config_folders.get(config_folder.casefold())
                if prior is not None:
                    errors.append(
                        f"packaged config_folder collision: {prior[0]}={prior[1]!r} and "
                        f"{core_id}={config_folder!r}"
                    )
                else:
                    packaged_config_folders[config_folder.casefold()] = (core_id, config_folder)
                expected_library_name = MLP1_PACKAGED_CORE_LIBRARY_NAMES.get(core_id)
                if expected_library_name is None:
                    errors.append(f"{core_id}: packaged core has no probed MLP1 library_name")
                elif config_folder != expected_library_name:
                    errors.append(
                        f"{core_id}: config_folder {config_folder!r} does not match probed "
                        f"library_name {expected_library_name!r}"
                    )
        elif not core.get("path"):
            errors.append(f"{core_id}: path core missing path")

    for system in systems.get("systems", []):
        system_id = system.get("id")
        default_core = system.get("default_core")
        if default_core not in core_ids:
            errors.append(f"{system_id}: default core not in cores catalog: {default_core}")
        for core_id in system.get("alternate_cores", []):
            if core_id not in core_ids:
                errors.append(f"{system_id}: alternate core not in cores catalog: {core_id}")
        legacy_flat_core = system.get("legacy_flat_core")
        expected_legacy_flat_core = LEGACY_FLAT_CORE_BY_SYSTEM.get(system_id)
        if legacy_flat_core != expected_legacy_flat_core:
            errors.append(
                f"{system_id}: legacy_flat_core must be {expected_legacy_flat_core!r}, "
                f"got {legacy_flat_core!r}"
            )
        if legacy_flat_core is not None:
            owner = core_by_id.get(legacy_flat_core)
            if owner is None:
                errors.append(f"{system_id}: legacy_flat_core not in cores catalog: {legacy_flat_core}")
            elif owner.get("type") != "retroarch" or owner.get("status") != "packaged":
                errors.append(
                    f"{system_id}: legacy_flat_core must name a packaged RetroArch core: "
                    f"{legacy_flat_core}"
                )
        for field in ("extensions", "archive_extensions", "archive_inner_extensions", "playlist_extensions"):
            for ext in system.get(field, []):
                if ext != ext.lower() or ext.startswith("."):
                    errors.append(f"{system_id}: invalid extension in {field}: {ext}")
        for name in system.get("ignore_file_names", []):
            if name != name.lower() or "/" in name or "\\" in name:
                errors.append(f"{system_id}: invalid ignore filename: {name}")

    errors.extend(validate_canonical_folders(systems, policy or {}))
    errors.extend(validate_system_core_overrides(systems, core_ids))
    return errors


def validate_system_core_overrides(
    systems: dict[str, Any], known_core_ids: set[str]
) -> list[str]:
    """Enforce canonical launch policy for override systems present in a catalog."""
    errors: list[str] = []
    rows_by_id = {
        row.get("id"): row
        for row in systems.get("systems", [])
        if isinstance(row, dict) and row.get("id")
    }
    for system_id, override in SYSTEM_CORE_OVERRIDES.items():
        row = rows_by_id.get(system_id)
        if row is None:
            continue
        expected_default = override["default_core"]
        if row.get("default_core") != expected_default:
            errors.append(
                f"{system_id}: default_core must be {expected_default!r}, "
                f"got {row.get('default_core')!r}"
            )
        expected_alternates = [
            core_id
            for core_id in override["alternate_cores"]
            if core_id in known_core_ids and core_id != expected_default
        ]
        if row.get("alternate_cores") != expected_alternates:
            errors.append(
                f"{system_id}: alternate_cores must be {expected_alternates!r}, "
                f"got {row.get('alternate_cores')!r}"
            )
    return errors


def validate_system_pattern_override(
    system_id: str,
    allium_console: dict[str, Any] | None,
    spruce_system: dict[str, Any] | None,
) -> list[str]:
    """Require every upstream alias hidden by an override to be reviewed."""
    ignored = IGNORED_SYSTEM_PATTERNS.get(system_id)
    if ignored is None:
        return [f"{system_id}: pattern override has no reviewed ignore list"]

    accepted = set(SYSTEM_PATTERN_OVERRIDES[system_id])
    overlap = accepted.intersection(ignored)
    errors = [
        f"{system_id}: patterns cannot be both accepted and ignored: {sorted(overlap)!r}"
    ] if overlap else []
    unreviewed = [
        pattern
        for pattern in source_system_patterns(system_id, allium_console, spruce_system)
        if pattern not in accepted and pattern not in ignored
    ]
    if unreviewed:
        errors.append(
            f"{system_id}: unreviewed upstream folder patterns: {unreviewed!r}"
        )
    return errors


def validate_system_pattern_overrides(inventory: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for system_id in SYSTEM_PATTERN_OVERRIDES:
        metadata_id = SYSTEM_METADATA_ALIASES.get(system_id, system_id)
        allium_console = retroarch_inventory.find_allium_console(
            inventory["allium"], metadata_id
        )
        spruce_system = retroarch_inventory.find_spruce_system(
            inventory["spruce"], metadata_id
        )
        errors.extend(
            validate_system_pattern_override(
                system_id, allium_console, spruce_system
            )
        )
    return errors


def validate_canonical_folders(systems: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    """Canonical user-folder invariants: one public folder per user library, no
    ambiguous folder routing, no alias/variant ids leaking out as public systems."""
    errors: list[str] = []
    rows = systems.get("systems", [])
    system_ids = {row.get("id") for row in rows}

    # One public folder per user library.
    seen_rom: dict[str, str] = {}
    seen_image: dict[str, str] = {}
    for row in rows:
        rid = row.get("id")
        rom_root = row.get("rom_root")
        image_root = row.get("image_root")
        if rom_root in seen_rom:
            errors.append(f"duplicate public rom_root {rom_root}: {seen_rom[rom_root]} and {rid}")
        else:
            seen_rom[rom_root] = rid
        if image_root in seen_image:
            errors.append(f"duplicate public image_root {image_root}: {seen_image[image_root]} and {rid}")
        else:
            seen_image[image_root] = rid

    # No two systems may claim the same folder pattern (ambiguous routing). This
    # is the check that catches alias rows that were not folded.
    pattern_owner: dict[str, str] = {}
    for row in rows:
        rid = row.get("id")
        for pattern in row.get("patterns", []):
            key = pattern.casefold()
            prior = pattern_owner.get(key)
            if prior is not None and prior != rid:
                errors.append(f"overlapping folder pattern {pattern!r}: claimed by {prior} and {rid}")
            else:
                pattern_owner[key] = rid

    # Alias/variant ids must never be emitted as their own public system.
    disallowed = set(policy.get("disallowed_public_system_ids", []))
    for entry in policy.get("systems", []):
        canonical_id = entry.get("canonical_id")
        if canonical_id not in system_ids:
            errors.append(f"policy canonical_id missing from catalog: {canonical_id}")
        for fold_id in entry.get("fold_ids", []):
            if fold_id in system_ids:
                errors.append(f"folded alias id emitted as public system: {fold_id} (should fold into {canonical_id})")
        disallowed.update(entry.get("variant_ids", []))
    for bad in sorted(disallowed):
        if bad in system_ids:
            errors.append(f"emulator-variant id emitted as public system: {bad}")

    return errors


def build_phase2_inventory(inventory: dict[str, Any], cores: dict[str, Any], systems: dict[str, Any]) -> dict[str, Any]:
    packaged = [core for core in cores["cores"] if core["status"] == "packaged"]
    missing = [core for core in cores["cores"] if core["status"] != "packaged"]
    return {
        "version": 1,
        "platform": "mlp1",
        "generated_by": "scripts/retroarch_generate_metadata.py",
        "source_core_count": len(inventory["umrk"].get("core_files", [])),
        "source_info_count": len(inventory["umrk"].get("info_files", [])),
        "generated_core_count": len(cores["cores"]),
        "generated_system_count": len(systems["systems"]),
        "packaged_core_count": len(packaged),
        "missing_core_count": len(missing),
        "packaged_core_ids": [core["id"] for core in packaged],
        "missing_core_ids": [core["id"] for core in missing],
        "warnings": inventory.get("warnings", []),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    root = repo_root_from_script()
    leaf_repo = leaf_repo_from_script()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--umrk-root", type=Path, default=root)
    parser.add_argument("--allium-root", type=Path, default=root / "Allium")
    parser.add_argument("--spruce-root", type=Path, default=root / "spruceOS")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=leaf_repo / "config/retroarch/mlp1",
    )
    parser.add_argument(
        "--build-report",
        type=Path,
        help=(
            "Complete probed Cores-spruce MLP1 build report. Defaults to "
            "<umrk-root>/Cores-spruce/output/mlp1/build-report.json."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    umrk_root = args.umrk_root.resolve()
    inventory = retroarch_inventory.build_inventory(
        umrk_root,
        args.allium_root.resolve(),
        args.spruce_root.resolve(),
    )
    stock_core_ids = parse_stock_parity_cores(umrk_root / "Cores-spruce/build-mlp1.sh")
    policy = load_system_folder_policy()
    cores = build_core_catalog(inventory, stock_core_ids)
    systems = build_system_catalog(inventory, cores, policy)
    errors = validate_generated(cores, systems, policy)
    errors.extend(validate_system_pattern_overrides(inventory))
    build_report_path = (
        args.build_report.resolve()
        if args.build_report is not None
        else umrk_root / "Cores-spruce/output/mlp1/build-report.json"
    )
    errors.extend(validate_build_report_contract(build_report_path, cores))
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    phase2_inventory = build_phase2_inventory(inventory, cores, systems)
    write_json(args.output_dir / "cores.json", cores)
    write_json(args.output_dir / "systems.json", systems)
    write_json(args.output_dir / "phase-2-inventory.json", phase2_inventory)

    print(f"Wrote {args.output_dir / 'cores.json'}")
    print(f"Wrote {args.output_dir / 'systems.json'}")
    print(f"Wrote {args.output_dir / 'phase-2-inventory.json'}")
    print(
        "Generated "
        f"{phase2_inventory['generated_core_count']} cores "
        f"({phase2_inventory['packaged_core_count']} packaged, "
        f"{phase2_inventory['missing_core_count']} missing) and "
        f"{phase2_inventory['generated_system_count']} systems"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
