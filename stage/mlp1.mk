# MLP1 staging recipes. Included by the top-level Makefile when DEVICE=mlp1.
# Dispatches to each sibling repo's own targets — does not reimplement builds.

# Apps staged by `make stage`.
STAGE_APPS ?= ssh-server Thing-File CentralScrutinizer Fugazi joes-calibrage retroarch-builds
STAGE_EMULATORS ?= ppsspp drastic mupen64plus flycast yabasanshiro
PUBLIC_ROOT_DIRS ?= Roms Images Videos Apps BIOS Saves States Cheats

# --- Launcher payload assembly inputs --------------------------------------
JAWAKA_BUILD_DIR ?= $(JAWAKA_DIR)/build/mlp1
JAWAKA_REQUIRE_SCREENSCRAPER ?= 1
DEVICE_OVERLAY   ?= $(LAUNCHER_SWITCHER_DIR)/device/mlp1
CATASTROPHE_ASSETS_DIR ?= $(CATASTROPHE_DIR)/res/assets
MLP1_RETROARCH_BIN ?= $(RETROARCH_BUILDS_DIR)/output/mlp1/bin/retroarch
MLP1_RETROARCH_MANIFEST ?= $(RETROARCH_BUILDS_DIR)/output/mlp1/build-manifest.json
MLP1_SHADERS_DIR    ?= $(RETROARCH_BUILDS_DIR)/output/mlp1/shaders
MLP1_SHADER_TOOL    ?= $(RETROARCH_BUILDS_DIR)/scripts/mlp1_shader_bundle.py
MLP1_ASSETS_DIR     ?= $(RETROARCH_BUILDS_DIR)/output/mlp1/assets
MLP1_ASSET_TOOL     ?= $(RETROARCH_BUILDS_DIR)/scripts/mlp1_asset_bundle.py
MLP1_CORES_DIR     ?= $(CORES_SPRUCE_DIR)/output/mlp1/cores
MLP1_CORES_REPORT  ?= $(CORES_SPRUCE_DIR)/output/mlp1/build-report.json
MLP1_CORE_TEST_REPORT ?= $(CORES_SPRUCE_DIR)/output/mlp1/targeted-build-report.json
MLP1_INFO_DIR      ?= $(CORES_SPRUCE_DIR)/output/mlp1/info
MLP1_METADATA_DIR  ?= $(UMRK_WORKSPACE_DIR)/plans/retroarch/generated/mlp1
MLP1_CORE_REPORT_TOOL ?= $(CORES_SPRUCE_DIR)/scripts/mlp1-core-report.py
MLP1_CORE_PROBE_RUNNER ?= $(CORES_SPRUCE_DIR)/probe-mlp1-cores-adb.sh
MLP1_PPSSPP_PACKAGE ?= $(PPSSPP_SPRUCE_DIR)/output/mlp1/ppsspp
MLP1_GRAPHICS_RUNTIME ?= $(LEAF_ROOT)/build/mlp1/runtime/graphics
MLP1_VULKAN_RUNTIME ?= $(MLP1_GRAPHICS_RUNTIME)/vulkan/rk3566-g52-g29p1
MLP1_DRASTIC_PACKAGE ?= $(LEAF_ROOT)/build/drastic/mlp1/drastic
MLP1_MUPEN64PLUS_PACKAGE ?= $(N64_STANDALONE_DIR)/output/mlp1/mupen64plus
MLP1_FLYCAST_PACKAGE ?= $(FLYCAST_STANDALONE_DIR)/output/mlp1/flycast
MLP1_YABASANSHIRO_PACKAGE ?= $(YABASANSHIRO_STANDALONE_DIR)/output/mlp1/yabasanshiro
MLP1_FFMPEG_BIN    ?= $(RETROARCH_BUILDS_DIR)/output/mlp1/ffmpeg/bin/ffmpeg
MLP1_FFMPEG_LIBS   ?= $(RETROARCH_BUILDS_DIR)/output/mlp1/ffmpeg/flat
MLP1_RECORD_CONVERT ?= $(RETROARCH_BUILDS_DIR)/config/mlp1/leaf-record-convert.sh
MLP1_RECORD_PRESET ?= $(RETROARCH_BUILDS_DIR)/config/mlp1/retroarch-record-rkmpp.cfg
MLP1_RETROARCH_PATCH_SET_FILE ?= $(LEAF_ROOT)/config/mlp1-retroarch-patch-set.txt
MLP1_RETROARCH_PATCH_SET ?= $(shell grep -v '^\#' "$(MLP1_RETROARCH_PATCH_SET_FILE)" | grep -v '^$$' | head -1)
MLP1_RETROARCH_VALIDATOR ?= $(LEAF_ROOT)/scripts/validate-mlp1-retroarch-build.py
UMRK_ENV_SCRIPT    ?= $(LAUNCHER_SWITCHER_DIR)/device/umrk-env.sh
REMOTE_SDCARD_PATH ?= auto
REMOTE_SYSTEM_PATH ?=
REMOTE_PLATFORM_PATH ?=
REMOTE_APPS_PATH ?=

# --- Leaf staging output (gitignored under /build) -------------------------
STAGE_BUILD          ?= $(LEAF_ROOT)/build/stage/mlp1
RELEASE_BUILD        ?= $(LEAF_ROOT)/build/release
PAYLOAD_ROOT         := $(STAGE_BUILD)/package
LEAF_SYSTEM_PAYLOAD_DIR := $(PAYLOAD_ROOT)/.system/leaf
PLATFORM_PAYLOAD_DIR := $(LEAF_SYSTEM_PAYLOAD_DIR)/platforms/mlp1
PAYLOAD_DIR          := $(PLATFORM_PAYLOAD_DIR)/launcher
export RELEASE_BUILD

# Command-line variables are automatically exported after recursive expansion.
# Capture TAG without rescanning it so an untrusted ref cannot invoke a Make
# function before the recipe's strict beta-tag validator sees it.
override LEAF_BETA_TAG_INPUT := $(value TAG)
unexport TAG
export LEAF_BETA_TAG_INPUT

.PHONY: stage stage-app stage-core-test stage-emulator stage-emulators stage-public-root stage-retroarch stage-refresh refresh-jawaka jawaka-build shader-bundle-mlp1 assemble-jawaka stage-jawaka release-zips release-sd-zip release-recovery-zip beta-zips verify-beta-zips stable-zips verify-stable-zips

# Build the Jawaka MLP1 binaries (cross-compile via its own Docker target).
jawaka-build:
	$(MAKE) -C "$(JAWAKA_DIR)" mlp1 \
		SCREENSCRAPER_REQUIRED="$(JAWAKA_REQUIRE_SCREENSCRAPER)" \
		WORKSPACE_ROOT="$(WORKSPACE_DIR)" \
		CATASTROPHE_DIR="$(CATASTROPHE_DIR)" \
		MLP1_TOOLCHAIN_IMAGE="$(TOOLCHAIN_IMAGE)"

shader-bundle-mlp1:
	$(MAKE) -C "$(RETROARCH_BUILDS_DIR)" shaders-mlp1 MLP1_SHADER_OUTPUT="$(MLP1_SHADERS_DIR)"
	python3 "$(MLP1_SHADER_TOOL)" validate --output "$(MLP1_SHADERS_DIR)"

# Assemble the launcher payload tree from Jawaka + Catastrophe + RetroArch +
# cores + shaders. Mirrors the former miniloong-launcher-switcher
# `jawaka-package` target; the device overlay still comes from
# launcher-switcher (device/mlp1 defaults).
assemble-jawaka: jawaka-build shader-bundle-mlp1
	$(MAKE) -C "$(CATASTROPHE_DIR)" assets
	@test -f "$(JAWAKA_BUILD_DIR)/build-manifest.json" || { echo "missing Jawaka MLP1 build manifest" >&2; exit 1; }
	@python3 -c 'import json,sys; data=json.load(open(sys.argv[1], encoding="utf-8")); sys.exit(0 if data.get("features", {}).get("screenscraper") is True else 1)' "$(JAWAKA_BUILD_DIR)/build-manifest.json" || { echo "refusing to assemble Jawaka without ScreenScraper support" >&2; exit 1; }
	@for scale in 1 2 3 4; do \
		asset="$(CATASTROPHE_ASSETS_DIR)/assets@$${scale}x.png"; \
		test -f "$$asset" || { echo "missing generated Catastrophe asset: $$asset" >&2; exit 1; }; \
	done
	@rm -rf "$(PAYLOAD_ROOT)"
	@mkdir -p "$(PAYLOAD_DIR)/bin" "$(PAYLOAD_DIR)/lib" "$(PAYLOAD_DIR)/res" "$(PLATFORM_PAYLOAD_DIR)"
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawakad" "$(PAYLOAD_DIR)/bin/loong_pangu"
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawaka-launcher" "$(PAYLOAD_DIR)/bin/jawaka-launcher"
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawaka-menu" "$(PAYLOAD_DIR)/bin/jawaka-menu"
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawaka-osd" "$(PAYLOAD_DIR)/bin/jawaka-osd"
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawaka-platformctl" "$(PAYLOAD_DIR)/bin/jawaka-platformctl"
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawaka-inhibitctl" "$(PAYLOAD_DIR)/bin/jawaka-inhibitctl"
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawaka-retroarchctl" "$(PAYLOAD_DIR)/bin/jawaka-retroarchctl"
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawaka-retroarch-runner" "$(PAYLOAD_DIR)/bin/jawaka-retroarch-runner"
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawaka-update-runner" "$(PAYLOAD_DIR)/bin/jawaka-update-runner"
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawaka-ledd" "$(PAYLOAD_DIR)/bin/jawaka-ledd"
	@chmod 755 "$(PAYLOAD_DIR)/bin/"*
	@if [ -f "$(JAWAKA_BUILD_DIR)/build-manifest.json" ]; then cp -f "$(JAWAKA_BUILD_DIR)/build-manifest.json" "$(PAYLOAD_DIR)/build-manifest.json"; fi
	@docker run --rm -v "$(PAYLOAD_DIR)/lib":/out "$(TOOLCHAIN_IMAGE)" bash -lc 'set -euo pipefail; for lib in libcurl.so.4 libssl.so.3 libcrypto.so.3 libz.so.1 libatomic.so.1; do src=""; for dir in "$$SYSROOT/usr/lib" "$$SYSROOT/lib"; do if [ -e "$$dir/$$lib" ]; then src="$$dir/$$lib"; break; fi; done; test -n "$$src" || { echo "missing SDK runtime library: $$lib" >&2; exit 1; }; cp -Lf "$$src" "/out/$$lib"; done'
	@chmod 755 "$(PAYLOAD_DIR)/lib/"*.so*
	@cp -f "$(UMRK_ENV_SCRIPT)" "$(PAYLOAD_DIR)/env.sh"
	@chmod 644 "$(PAYLOAD_DIR)/env.sh"
	@cp -Rf "$(JAWAKA_DIR)/res/themes" "$(PAYLOAD_DIR)/res/"
	@if [ -d "$(JAWAKA_DIR)/res/system_icons" ]; then cp -Rf "$(JAWAKA_DIR)/res/system_icons" "$(PAYLOAD_DIR)/res/"; fi
	@if [ -f "$(JAWAKA_DIR)/res/certs/cacert.pem" ]; then mkdir -p "$(PAYLOAD_DIR)/res/certs"; cp -f "$(JAWAKA_DIR)/res/certs/cacert.pem" "$(PAYLOAD_DIR)/res/certs/cacert.pem"; fi
	@if [ -d "$(JAWAKA_DIR)/res/sounds" ]; then cp -Rf "$(JAWAKA_DIR)/res/sounds" "$(PAYLOAD_DIR)/res/"; fi
	@cp -Rf "$(CATASTROPHE_DIR)/res/fonts" "$(PAYLOAD_DIR)/res/"
	@cp -f "$(CATASTROPHE_DIR)/res/font.ttf" "$(PAYLOAD_DIR)/res/font.ttf"
	@cp -Rf "$(CATASTROPHE_ASSETS_DIR)" "$(PAYLOAD_DIR)/res/assets"
	@cp -Rf "$(DEVICE_OVERLAY)/." "$(PLATFORM_PAYLOAD_DIR)/"
	@test -f "$(PLATFORM_PAYLOAD_DIR)/defaults/systems.json" || { echo "missing platform defaults: $(PLATFORM_PAYLOAD_DIR)/defaults/systems.json" >&2; exit 1; }
	@test -f "$(PLATFORM_PAYLOAD_DIR)/defaults/cores.json" || { echo "missing platform defaults: $(PLATFORM_PAYLOAD_DIR)/defaults/cores.json" >&2; exit 1; }
	@# Compiled UI translations. The launcher reads $$UMRK_PLATFORM_PATH/i18n;
	@# the compiler drops fuzzy entries (unreviewed strings never ship), and a
	@# table that would ship zero entries is skipped entirely -- shipping it
	@# would make the Settings language picker offer a language that translates
	@# nothing. The hand-editable .tsv override in .umrk still outranks this at
	@# runtime, so a translator can keep iterating on top of a release.
	@mkdir -p "$(PLATFORM_PAYLOAD_DIR)/i18n"
	@for po in "$(JAWAKA_DIR)"/i18n/*.po; do \
		[ -f "$$po" ] || continue; \
		code=$$(basename "$$po" .po); \
		out="$(PLATFORM_PAYLOAD_DIR)/i18n/$$code.jwi"; \
		python3 "$(JAWAKA_DIR)/tools/i18n-compile.py" "$$po" -o "$$out" || exit 1; \
		if [ "$$(wc -c < "$$out")" -le 25 ]; then \
			echo "skipping $$code: no reviewed entries to ship"; rm -f "$$out"; \
		fi; \
	done
	@mkdir -p "$(PLATFORM_PAYLOAD_DIR)/platform.d"
	@if [ -d "$(JAWAKA_DIR)/platform/mlp1/platform.d" ]; then \
		cp -Rf "$(JAWAKA_DIR)/platform/mlp1/platform.d/." "$(PLATFORM_PAYLOAD_DIR)/platform.d/"; \
		find "$(PLATFORM_PAYLOAD_DIR)/platform.d" -type f -exec chmod 755 {} \;; \
	fi
	@if [ -f "$(MLP1_RETROARCH_BIN)" ]; then \
		python3 "$(MLP1_RETROARCH_VALIDATOR)" \
			--binary "$(MLP1_RETROARCH_BIN)" \
			--manifest "$(MLP1_RETROARCH_MANIFEST)" \
			--expected-patch-set "$(MLP1_RETROARCH_PATCH_SET)" \
		|| { echo "refusing to stage an unverified RetroArch; run: make stage-retroarch DEVICE=mlp1" >&2; exit 1; }; \
		mkdir -p "$(PLATFORM_PAYLOAD_DIR)/bin"; \
		cp -f "$(MLP1_RETROARCH_BIN)" "$(PLATFORM_PAYLOAD_DIR)/bin/retroarch"; \
		cp -f "$(MLP1_RETROARCH_MANIFEST)" "$(PLATFORM_PAYLOAD_DIR)/bin/retroarch.build-manifest.json"; \
		chmod 755 "$(PLATFORM_PAYLOAD_DIR)/bin/retroarch"; \
	else \
		echo "warning: MLP1 RetroArch not found at $(MLP1_RETROARCH_BIN); launches will fail until built (make stage-retroarch)."; \
	fi
	@# Recording payload. RetroArch reaches these libraries through a RUNPATH of
	@# $$ORIGIN/../lib/ffmpeg, so bin/ and lib/ffmpeg/ must stay siblings -- moving
	@# either breaks recording with a loader error and nothing more informative.
	@# The libraries are already flattened to one real file per SONAME because the
	@# SD card is FAT32 and cannot carry ffmpeg's usual symlink chain.
	@if [ -f "$(MLP1_FFMPEG_BIN)" ] && [ -d "$(MLP1_FFMPEG_LIBS)" ]; then \
		mkdir -p "$(PLATFORM_PAYLOAD_DIR)/bin" "$(PLATFORM_PAYLOAD_DIR)/lib/ffmpeg"; \
		cp -f "$(MLP1_FFMPEG_BIN)" "$(PLATFORM_PAYLOAD_DIR)/bin/ffmpeg"; \
		chmod 755 "$(PLATFORM_PAYLOAD_DIR)/bin/ffmpeg"; \
		find "$(MLP1_FFMPEG_LIBS)" -maxdepth 1 -type f -name '*.so.*' -exec cp -f {} "$(PLATFORM_PAYLOAD_DIR)/lib/ffmpeg/" \;; \
		chmod 755 "$(PLATFORM_PAYLOAD_DIR)/lib/ffmpeg/"*.so.* 2>/dev/null || true; \
		test -f "$(MLP1_RECORD_CONVERT)" || { echo "missing record convert script: $(MLP1_RECORD_CONVERT)" >&2; exit 1; }; \
		cp -f "$(MLP1_RECORD_CONVERT)" "$(PLATFORM_PAYLOAD_DIR)/bin/leaf-record-convert.sh"; \
		chmod 755 "$(PLATFORM_PAYLOAD_DIR)/bin/leaf-record-convert.sh"; \
		test -f "$(MLP1_RECORD_PRESET)" || { echo "missing record preset: $(MLP1_RECORD_PRESET)" >&2; exit 1; }; \
		mkdir -p "$(PLATFORM_PAYLOAD_DIR)/defaults"; \
		cp -f "$(MLP1_RECORD_PRESET)" "$(PLATFORM_PAYLOAD_DIR)/defaults/retroarch-record.cfg"; \
	else \
		echo "warning: MLP1 FFmpeg not found at $(MLP1_FFMPEG_BIN); game recording will be unavailable (run retroarch-builds/build-mlp1-ffmpeg.sh)."; \
	fi
	@if [ -d "$(MLP1_CORES_DIR)" ]; then \
		mkdir -p "$(PLATFORM_PAYLOAD_DIR)/cores"; \
		find "$(MLP1_CORES_DIR)" -maxdepth 1 -type f -name '*_libretro.so' -exec cp -f {} "$(PLATFORM_PAYLOAD_DIR)/cores/" \;; \
		if [ -f "$(MLP1_CORES_REPORT)" ]; then cp -f "$(MLP1_CORES_REPORT)" "$(PLATFORM_PAYLOAD_DIR)/cores/build-report.json"; fi; \
		chmod 755 "$(PLATFORM_PAYLOAD_DIR)/cores/"*_libretro.so 2>/dev/null || true; \
	else \
		echo "warning: MLP1 cores not found at $(MLP1_CORES_DIR); launches will fail until built (make stage-retroarch)."; \
	fi
	@if [ -d "$(MLP1_INFO_DIR)" ]; then \
		mkdir -p "$(PLATFORM_PAYLOAD_DIR)/info"; \
		find "$(MLP1_INFO_DIR)" -maxdepth 1 -type f -name '*_libretro.info' -exec cp -f {} "$(PLATFORM_PAYLOAD_DIR)/info/" \;; \
	fi
	@test -d "$(MLP1_SHADERS_DIR)" || { echo "missing MLP1 shader bundle: $(MLP1_SHADERS_DIR)" >&2; exit 1; }
	@mkdir -p "$(PLATFORM_PAYLOAD_DIR)/shaders"
	@cp -Rf "$(MLP1_SHADERS_DIR)/." "$(PLATFORM_PAYLOAD_DIR)/shaders/"
	@python3 "$(MLP1_SHADER_TOOL)" validate --output "$(PLATFORM_PAYLOAD_DIR)/shaders"
	@# RetroArch menu assets. Ozone reads every icon and font it draws from
	@# assets_directory, which jawaka-retroarch-runner points here; without this
	@# tree Ozone has no icons and falls back to a bitmap font that cannot draw CJK.
	@test -d "$(MLP1_ASSETS_DIR)" || { echo "missing MLP1 asset bundle: $(MLP1_ASSETS_DIR)" >&2; exit 1; }
	@mkdir -p "$(PLATFORM_PAYLOAD_DIR)/assets"
	@cp -Rf "$(MLP1_ASSETS_DIR)/." "$(PLATFORM_PAYLOAD_DIR)/assets/"
	@python3 "$(MLP1_ASSET_TOOL)" validate --output "$(PLATFORM_PAYLOAD_DIR)/assets"
	@test -f "$(PLATFORM_PAYLOAD_DIR)/cores/build-report.json" || { echo "missing MLP1 core build report: $(PLATFORM_PAYLOAD_DIR)/cores/build-report.json" >&2; exit 1; }
	@python3 "$(UMRK_WORKSPACE_DIR)/scripts/retroarch_validate_package.py" \
		--umrk-root "$(WORKSPACE_DIR)" \
		--metadata-dir "$(MLP1_METADATA_DIR)" \
		--build-report "$(PLATFORM_PAYLOAD_DIR)/cores/build-report.json" \
		--package-root "$(PLATFORM_PAYLOAD_DIR)"
	@# Jawaka owns which controllers an emulator may see. A wrapper that
	@# overwrites the published roster, or code that opens an event node
	@# directly, fails silently at runtime -- the player just gets the wrong
	@# pad -- so it is gated here instead.
	@python3 "$(LEAF_ROOT)/scripts/validate-input-roster-policy.py" \
		"$(PLATFORM_PAYLOAD_DIR)"
	@printf 'Jawaka MLP1 launcher bundle\n' > "$(PAYLOAD_DIR)/README.txt"
	@echo "Assembled payload at $(PAYLOAD_ROOT)"
	@find "$(PAYLOAD_ROOT)" -type f | sort

# Assemble + stage the launcher payload to the device via Leaf's ADB script
# (BUNDLE_ROOT points at the centrally-assembled payload).
stage-jawaka: assemble-jawaka
	DEVICE="$(DEVICE)" PLATFORM_ID="mlp1" REMOTE_SDCARD_PATH="$(REMOTE_SDCARD_PATH)" REMOTE_SYSTEM_PATH="$(REMOTE_SYSTEM_PATH)" REMOTE_PLATFORM_PATH="$(REMOTE_PLATFORM_PATH)" BUNDLE_ROOT="$(PAYLOAD_ROOT)" "$(LEAF_ROOT)/scripts/adb-stage-sd-bundle.sh" --marker

# Build or reuse the current MLP1 RetroArch/core outputs, then refresh only the
# platform runtime folders on the SD card.
stage-retroarch:
	@if ! python3 "$(MLP1_RETROARCH_VALIDATOR)" \
			--binary "$(MLP1_RETROARCH_BIN)" \
			--manifest "$(MLP1_RETROARCH_MANIFEST)" \
			--expected-patch-set "$(MLP1_RETROARCH_PATCH_SET)"; then \
		echo "building MLP1 RetroArch in $(RETROARCH_BUILDS_DIR)"; \
		cd "$(RETROARCH_BUILDS_DIR)" && MLP1_PATCH_SET="$(MLP1_RETROARCH_PATCH_SET)" ./build-mlp1.sh; \
		cd "$(LEAF_ROOT)" && python3 "$(MLP1_RETROARCH_VALIDATOR)" \
			--binary "$(MLP1_RETROARCH_BIN)" \
			--manifest "$(MLP1_RETROARCH_MANIFEST)" \
			--expected-patch-set "$(MLP1_RETROARCH_PATCH_SET)"; \
	fi
	@REBUILD_CORES="$(REBUILD_CORES)" \
		FORCE_REBUILD_CORES="$(FORCE_REBUILD_CORES)" \
		CORES_SPRUCE_DIR="$(CORES_SPRUCE_DIR)" \
		MLP1_CORES_DIR="$(MLP1_CORES_DIR)" \
		MLP1_CORES_REPORT="$(MLP1_CORES_REPORT)" \
		MLP1_CORE_REPORT_TOOL="$(MLP1_CORE_REPORT_TOOL)" \
		"$(LEAF_ROOT)/scripts/ensure-mlp1-cores.sh"
	@test -f "$(MLP1_RETROARCH_BIN)" || { echo "missing RetroArch binary: $(MLP1_RETROARCH_BIN)" >&2; exit 1; }
	@test -d "$(MLP1_CORES_DIR)" || { echo "missing cores dir: $(MLP1_CORES_DIR)" >&2; exit 1; }
	@$(MAKE) -C "$(RETROARCH_BUILDS_DIR)" shaders-mlp1 MLP1_SHADER_OUTPUT="$(MLP1_SHADERS_DIR)"
	@python3 "$(MLP1_SHADER_TOOL)" validate --output "$(MLP1_SHADERS_DIR)"
	@$(MAKE) -C "$(RETROARCH_BUILDS_DIR)" assets-mlp1 MLP1_ASSET_OUTPUT="$(MLP1_ASSETS_DIR)"
	@python3 "$(MLP1_ASSET_TOOL)" validate --output "$(MLP1_ASSETS_DIR)"
	@if ! python3 "$(MLP1_CORE_REPORT_TOOL)" verify \
			--report "$(MLP1_CORES_REPORT)" \
			--cores-dir "$(MLP1_CORES_DIR)"; then \
		echo "Probing exact MLP1 libretro library names on the selected device"; \
		ADB_SERIAL="$${ADB_SERIAL:-}" "$(MLP1_CORE_PROBE_RUNNER)" \
			--report "$(MLP1_CORES_REPORT)" \
			--cores-dir "$(MLP1_CORES_DIR)"; \
	fi
	@python3 "$(MLP1_CORE_REPORT_TOOL)" verify \
		--report "$(MLP1_CORES_REPORT)" \
		--cores-dir "$(MLP1_CORES_DIR)"
	@python3 "$(UMRK_WORKSPACE_DIR)/scripts/retroarch_validate_package.py" \
		--metadata-dir "$(MLP1_METADATA_DIR)" \
		--build-report "$(MLP1_CORES_REPORT)" \
		--require-full-build-report
	@set -euo pipefail; \
	if [ -n "$${ADB_SERIAL:-}" ]; then \
		serial="$$ADB_SERIAL"; \
	else \
		serial="$$(adb devices | awk 'NR>1 && $$2=="device" {print $$1; exit}')"; \
	fi; \
	if [ -z "$$serial" ]; then \
		echo "No online adb device found." >&2; \
		exit 1; \
	fi; \
	ADB=(adb -s "$$serial"); \
	echo "Using adb device: $$serial"; \
	remote_sd="$$(PLATFORM_ID="mlp1" REMOTE_SDCARD_PATH="$(REMOTE_SDCARD_PATH)" ADB_SERIAL="$$serial" "$(LEAF_ROOT)/scripts/adb-resolve-umrk-sd.sh")"; \
	remote_system="$(REMOTE_SYSTEM_PATH)"; \
	if [ -z "$$remote_system" ]; then remote_system="$$remote_sd/.system/leaf"; fi; \
	remote_platform="$(REMOTE_PLATFORM_PATH)"; \
	if [ -z "$$remote_platform" ]; then remote_platform="$$remote_system/platforms/mlp1"; fi; \
	ADB_SERIAL="$$serial" PLATFORM_ID="mlp1" \
		REMOTE_SDCARD_PATH="$$remote_sd" \
		REMOTE_SYSTEM_PATH="$$remote_system" \
		REMOTE_PLATFORM_PATH="$$remote_platform" \
		"$(LEAF_ROOT)/scripts/adb-sync-shader-namespaces.sh" --migrate-only; \
	"$${ADB[@]}" shell "mkdir -p '$$remote_platform' && rm -rf '$$remote_platform/bin' '$$remote_platform/cores' '$$remote_platform/info' '$$remote_platform/shaders' '$$remote_platform/assets' && mkdir -p '$$remote_platform/bin' '$$remote_platform/cores' '$$remote_platform/info' '$$remote_platform/shaders' '$$remote_platform/assets'"; \
	"$${ADB[@]}" push "$(MLP1_RETROARCH_BIN)" "$$remote_platform/bin/retroarch" >/dev/null; \
	if [ -f "$(MLP1_RETROARCH_MANIFEST)" ]; then \
		"$${ADB[@]}" push "$(MLP1_RETROARCH_MANIFEST)" "$$remote_platform/bin/retroarch.build-manifest.json" >/dev/null; \
	fi; \
	"$${ADB[@]}" push "$(MLP1_CORES_DIR)/." "$$remote_platform/cores/" >/dev/null; \
	if [ -f "$(MLP1_CORES_REPORT)" ]; then \
		"$${ADB[@]}" push "$(MLP1_CORES_REPORT)" "$$remote_platform/cores/build-report.json" >/dev/null; \
	fi; \
	if [ -d "$(MLP1_INFO_DIR)" ]; then \
		"$${ADB[@]}" push "$(MLP1_INFO_DIR)/." "$$remote_platform/info/" >/dev/null; \
	fi; \
	"$${ADB[@]}" push "$(MLP1_SHADERS_DIR)/." "$$remote_platform/shaders/" >/dev/null; \
	"$${ADB[@]}" push "$(MLP1_ASSETS_DIR)/." "$$remote_platform/assets/" >/dev/null; \
	ADB_SERIAL="$$serial" PLATFORM_ID="mlp1" \
		REMOTE_SDCARD_PATH="$$remote_sd" \
		REMOTE_SYSTEM_PATH="$$remote_system" \
		REMOTE_PLATFORM_PATH="$$remote_platform" \
		"$(LEAF_ROOT)/scripts/adb-sync-shader-namespaces.sh" --sync-only; \
	ADB_SERIAL="$$serial" PLATFORM_ID="mlp1" \
		REMOTE_SDCARD_PATH="$$remote_sd" \
		REMOTE_SYSTEM_PATH="$$remote_system" \
		REMOTE_PLATFORM_PATH="$$remote_platform" \
		"$(LEAF_ROOT)/scripts/adb-sync-asset-namespaces.sh"; \
	"$${ADB[@]}" shell "chmod 755 '$$remote_platform/bin/retroarch' '$$remote_platform/cores/'*_libretro.so 2>/dev/null || true"; \
	"$${ADB[@]}" shell sync; \
	echo "RetroArch platform payload staged."

# Testing-only fast path for a targeted core build. It never replaces the
# device's full build report or any sibling core; release staging remains gated
# by stage-retroarch's complete stock-parity report.
stage-core-test:
	@set -euo pipefail; \
	core="$(CORE)"; \
	case "$$core" in ''|*[!a-z0-9_]*) echo "usage: make stage-core-test CORE=<core-id> DEVICE=mlp1" >&2; exit 2;; esac; \
	if ! python3 "$(MLP1_CORE_REPORT_TOOL)" verify \
			--report "$(MLP1_CORE_TEST_REPORT)" \
			--cores-dir "$(MLP1_CORES_DIR)" >/dev/null 2>&1; then \
		echo "Probing targeted MLP1 build report on the selected device"; \
		ADB_SERIAL="$${ADB_SERIAL:-}" "$(MLP1_CORE_PROBE_RUNNER)" \
			--report "$(MLP1_CORE_TEST_REPORT)" \
			--cores-dir "$(MLP1_CORES_DIR)"; \
	fi; \
	python3 "$(MLP1_CORE_REPORT_TOOL)" verify \
		--report "$(MLP1_CORE_TEST_REPORT)" \
		--cores-dir "$(MLP1_CORES_DIR)"; \
	row="$$(python3 "$(MLP1_CORE_REPORT_TOOL)" manifest \
		--report "$(MLP1_CORE_TEST_REPORT)" \
		--cores-dir "$(MLP1_CORES_DIR)" | awk -F '\t' -v wanted="$$core" '$$1 == wanted { print; exit }')"; \
	[ -n "$$row" ] || { echo "error: targeted report does not contain core: $$core" >&2; exit 2; }; \
	IFS=$$'\t' read -r _ core_file expected_sha256 <<<"$$row"; \
	info_file="$${core_file%.so}.info"; \
	core_path="$(MLP1_CORES_DIR)/$$core_file"; \
	info_path="$(MLP1_INFO_DIR)/$$info_file"; \
	[ -f "$$info_path" ] || { echo "error: missing matching info file: $$info_path" >&2; exit 2; }; \
	if [ -n "$${ADB_SERIAL:-}" ]; then serial="$$ADB_SERIAL"; else serial="$$(adb devices | awk 'NR>1 && $$2=="device" {print $$1; exit}')"; fi; \
	[ -n "$$serial" ] || { echo "No online adb device found." >&2; exit 1; }; \
	ADB=(adb -s "$$serial"); \
	if "$${ADB[@]}" shell 'pidof retroarch >/dev/null'; then \
		echo "error: exit the running RetroArch game before replacing $$core_file" >&2; \
		exit 2; \
	fi; \
	remote_sd="$$(PLATFORM_ID="mlp1" REMOTE_SDCARD_PATH="$(REMOTE_SDCARD_PATH)" ADB_SERIAL="$$serial" "$(LEAF_ROOT)/scripts/adb-resolve-umrk-sd.sh")"; \
	remote_system="$(REMOTE_SYSTEM_PATH)"; \
	if [ -z "$$remote_system" ]; then remote_system="$$remote_sd/.system/leaf"; fi; \
	remote_platform="$(REMOTE_PLATFORM_PATH)"; \
	if [ -z "$$remote_platform" ]; then remote_platform="$$remote_system/platforms/mlp1"; fi; \
	"$${ADB[@]}" shell "mkdir -p '$$remote_platform/cores' '$$remote_platform/info'"; \
	"$${ADB[@]}" push "$$core_path" "$$remote_platform/cores/$$core_file" >/dev/null; \
	"$${ADB[@]}" push "$$info_path" "$$remote_platform/info/$$info_file" >/dev/null; \
	"$${ADB[@]}" shell "chmod 755 '$$remote_platform/cores/$$core_file' && sync"; \
	actual_sha256="$$("$${ADB[@]}" shell "sha256sum '$$remote_platform/cores/$$core_file'" | awk '{print $$1}')"; \
	[ "$$actual_sha256" = "$$expected_sha256" ] || { echo "error: device checksum mismatch for $$core_file" >&2; exit 1; }; \
	echo "Testing core staged: $$core ($$expected_sha256)"

# Create the public SD folders Leaf exposes to users. Internal runtime files live
# under .system/leaf; these directories stay at the card root for content.
stage-public-root:
	@set -euo pipefail; \
	if [ -n "$${ADB_SERIAL:-}" ]; then \
		serial="$$ADB_SERIAL"; \
	else \
		serial="$$(adb devices | awk 'NR>1 && $$2=="device" {print $$1; exit}')"; \
	fi; \
	if [ -z "$$serial" ]; then \
		echo "No online adb device found." >&2; \
		exit 1; \
	fi; \
	ADB=(adb -s "$$serial"); \
	echo "Using adb device: $$serial"; \
	remote_sd="$$(PLATFORM_ID="mlp1" REMOTE_SDCARD_PATH="$(REMOTE_SDCARD_PATH)" ADB_SERIAL="$$serial" "$(LEAF_ROOT)/scripts/adb-resolve-umrk-sd.sh")"; \
	mkdirs=""; \
	for dir in $(PUBLIC_ROOT_DIRS); do \
		mkdirs="$$mkdirs '$$remote_sd/$$dir'"; \
	done; \
	"$${ADB[@]}" shell "mkdir -p $$mkdirs && sync"; \
	echo "Public SD folders ready at $$remote_sd: $(PUBLIC_ROOT_DIRS)"

# Stage a single standalone emulator payload to the device. Product repos own
# package output; Leaf owns SD resolution and deployment location.
#   make stage-emulator EMULATOR=ppsspp DEVICE=mlp1
stage-emulator:
	@test -n "$(EMULATOR)" || { echo "usage: make stage-emulator EMULATOR=<id> DEVICE=mlp1" >&2; exit 1; }
	@set -euo pipefail; \
	case "$(EMULATOR)" in \
		ppsspp) \
			test -d "$(PPSSPP_SPRUCE_DIR)" || { echo "missing repo: $(PPSSPP_SPRUCE_DIR) (run: make bootstrap)" >&2; exit 1; }; \
			MLP1_GRAPHICS_RUNTIME_DIR="$(MLP1_GRAPHICS_RUNTIME)" \
				"$(LEAF_ROOT)/scripts/build-mlp1-graphics-runtime.sh"; \
			$(MAKE) -C "$(PPSSPP_SPRUCE_DIR)" package-mlp1; \
			package_dir="$(MLP1_PPSSPP_PACKAGE)"; \
			remote_name="ppsspp"; \
			vulkan_runtime="$(MLP1_VULKAN_RUNTIME)"; \
			;; \
		drastic) \
			test -d "$(STEWARD_NDS_DIR)" || { echo "missing repo: $(STEWARD_NDS_DIR) (run: make bootstrap)" >&2; exit 1; }; \
			OUTPUT_DIR="$(MLP1_DRASTIC_PACKAGE)" \
			STEWARD_NDS_DIR="$(STEWARD_NDS_DIR)" \
			TOOLCHAIN_IMAGE="$(TOOLCHAIN_IMAGE)" \
				"$(LEAF_ROOT)/scripts/package-drastic-mlp1.sh"; \
			package_dir="$(MLP1_DRASTIC_PACKAGE)"; \
			remote_name="drastic"; \
			;; \
		mupen64plus) \
			test -d "$(N64_STANDALONE_DIR)" || { echo "missing repo: $(N64_STANDALONE_DIR)" >&2; exit 1; }; \
			$(MAKE) -C "$(N64_STANDALONE_DIR)" package-mlp1 TOOLCHAIN_IMAGE="$(TOOLCHAIN_IMAGE)"; \
			package_dir="$(MLP1_MUPEN64PLUS_PACKAGE)"; \
			remote_name="mupen64plus"; \
			;; \
		flycast) \
			test -d "$(FLYCAST_STANDALONE_DIR)" || { echo "missing repo: $(FLYCAST_STANDALONE_DIR)" >&2; exit 1; }; \
			$(MAKE) -C "$(FLYCAST_STANDALONE_DIR)" package-mlp1 TOOLCHAIN_IMAGE="$(TOOLCHAIN_IMAGE)"; \
			package_dir="$(MLP1_FLYCAST_PACKAGE)"; \
			remote_name="flycast"; \
			;; \
		yabasanshiro) \
			test -d "$(YABASANSHIRO_STANDALONE_DIR)" || { echo "missing repo: $(YABASANSHIRO_STANDALONE_DIR)" >&2; exit 1; }; \
			$(MAKE) -C "$(YABASANSHIRO_STANDALONE_DIR)" package-mlp1 TOOLCHAIN_IMAGE="$(TOOLCHAIN_IMAGE)"; \
			package_dir="$(MLP1_YABASANSHIRO_PACKAGE)"; \
			remote_name="yabasanshiro"; \
			;; \
		*) \
			echo "unsupported emulator policy: $(EMULATOR) for DEVICE=$(DEVICE)" >&2; \
			exit 1; \
			;; \
	esac; \
	test -d "$$package_dir" || { echo "missing emulator package dir: $$package_dir" >&2; exit 1; }; \
	if [ -n "$${ADB_SERIAL:-}" ]; then \
		serial="$$ADB_SERIAL"; \
	else \
		serial="$$(adb devices | awk 'NR>1 && $$2=="device" {print $$1; exit}')"; \
	fi; \
	if [ -z "$$serial" ]; then \
		echo "No online adb device found." >&2; \
		exit 1; \
	fi; \
	ADB=(adb -s "$$serial"); \
	echo "Using adb device: $$serial"; \
	remote_sd="$$(PLATFORM_ID="mlp1" REMOTE_SDCARD_PATH="$(REMOTE_SDCARD_PATH)" ADB_SERIAL="$$serial" "$(LEAF_ROOT)/scripts/adb-resolve-umrk-sd.sh")"; \
	remote_system="$(REMOTE_SYSTEM_PATH)"; \
	if [ -z "$$remote_system" ]; then remote_system="$$remote_sd/.system/leaf"; fi; \
	remote_platform="$(REMOTE_PLATFORM_PATH)"; \
	if [ -z "$$remote_platform" ]; then remote_platform="$$remote_system/platforms/mlp1"; fi; \
	if [ -n "$${vulkan_runtime:-}" ]; then \
		test -d "$$vulkan_runtime" || { echo "missing Vulkan runtime: $$vulkan_runtime" >&2; exit 1; }; \
		remote_vulkan="$$remote_platform/runtime/graphics/vulkan/rk3566-g52-g29p1"; \
		echo "Deploying shared Vulkan runtime to $$remote_vulkan"; \
		"$${ADB[@]}" shell "rm -rf \"$$remote_vulkan\" && mkdir -p \"$$remote_vulkan\""; \
		"$${ADB[@]}" push "$$vulkan_runtime/." "$$remote_vulkan/" >/dev/null; \
	fi; \
	python3 "$(LEAF_ROOT)/scripts/validate-input-roster-policy.py" "$$package_dir"; \
	remote_dir="$$remote_platform/emulators/$$remote_name"; \
	echo "Deploying $(EMULATOR) emulator to $$remote_dir"; \
	"$${ADB[@]}" shell "rm -rf \"$$remote_dir\" && mkdir -p \"$$remote_dir\""; \
	"$${ADB[@]}" push "$$package_dir/." "$$remote_dir/" >/dev/null; \
	"$${ADB[@]}" shell "chmod 755 \"$$remote_dir\"/launch*.sh \"$$remote_dir/bin/\"* \"$$remote_dir/lib/\"* 2>/dev/null || true"; \
	if [ -d "$(DEVICE_OVERLAY)/defaults" ]; then \
		echo "Refreshing platform defaults at $$remote_platform/defaults"; \
		"$${ADB[@]}" shell "rm -rf '$$remote_platform/defaults' && mkdir -p '$$remote_platform/defaults'"; \
		"$${ADB[@]}" push "$(DEVICE_OVERLAY)/defaults/." "$$remote_platform/defaults/" >/dev/null; \
	fi; \
	"$${ADB[@]}" shell "test -f '$$remote_platform/defaults/systems.json' && test -f '$$remote_platform/defaults/cores.json'" || { echo "missing platform defaults at $$remote_platform/defaults" >&2; exit 1; }; \
	"$${ADB[@]}" shell sync; \
	"$${ADB[@]}" shell "find '$$remote_dir' -maxdepth 3 -type f | sort | sed -n '1,80p'"

stage-emulators:
	@set -euo pipefail; \
	emulators="$(STAGE_EMULATORS)"; \
	if [ -n "$$emulators" ]; then \
		for emulator in $$emulators; do \
			$(MAKE) stage-emulator EMULATOR="$$emulator" DEVICE="$(DEVICE)"; \
		done; \
	fi

# Full device stage: public folders first, RetroArch/cores next, standalone
# emulators next, launcher payload next, then each app package.
stage: stage-public-root stage-retroarch stage-emulators stage-jawaka
	@set -euo pipefail; \
	apps="$(STAGE_APPS)"; \
	if [ -n "$$apps" ]; then \
		for app in $$apps; do \
			$(MAKE) stage-app APP="$$app" DEVICE="$(DEVICE)"; \
		done; \
	fi

# Full device stage, then restart the Loong/Jawaka launcher stack.
stage-refresh: stage refresh-jawaka

# Restart the active MLP1 GUI stack. Under the init-hook model, a reboot is the
# normal way to exercise a newly staged Leaf bundle.
refresh-jawaka:
	"$(LEAF_ROOT)/scripts/adb-restart-loong.sh"

# Stage a single app repo to the device. Product repos still own package
# targets; Leaf owns SD resolution and pushing the package to Apps.
#   make stage-app APP=ssh-server DEVICE=mlp1
stage-app:
	@test -n "$(APP)" || { echo "usage: make stage-app APP=<repo> DEVICE=mlp1" >&2; exit 1; }
	@test -d "$(WORKSPACE_DIR)/$(APP)" || { echo "missing repo: $(WORKSPACE_DIR)/$(APP) (run: make bootstrap)" >&2; exit 1; }
	@set -euo pipefail; \
	. "$(LEAF_ROOT)/scripts/app-package-policy.sh"; \
	leaf_app_policy "$(APP)" "$(WORKSPACE_DIR)" "$(DEVICE)" || { echo "unsupported app policy: $(APP) for DEVICE=$(DEVICE)" >&2; exit 1; }; \
	make_args=("$$package_target"); \
	if [ -n "$${package_platform:-}" ]; then make_args+=("PLATFORM=$$package_platform"); fi; \
	$(MAKE) -C "$(WORKSPACE_DIR)/$(APP)" "$${make_args[@]}"; \
	test -d "$$package_dir" || { echo "missing package dir: $$package_dir" >&2; exit 1; }; \
	if [ -n "$${ADB_SERIAL:-}" ]; then \
		serial="$$ADB_SERIAL"; \
	else \
		serial="$$(adb devices | awk 'NR>1 && $$2=="device" {print $$1; exit}')"; \
	fi; \
	if [ -z "$$serial" ]; then \
		echo "No online adb device found." >&2; \
		exit 1; \
	fi; \
	ADB=(adb -s "$$serial"); \
	echo "Using adb device: $$serial"; \
	remote_sd="$$(PLATFORM_ID="mlp1" REMOTE_SDCARD_PATH="$(REMOTE_SDCARD_PATH)" ADB_SERIAL="$$serial" "$(LEAF_ROOT)/scripts/adb-resolve-umrk-sd.sh")"; \
	remote_apps="$(REMOTE_APPS_PATH)"; \
	if [ -z "$$remote_apps" ]; then remote_apps="$$remote_sd/Apps"; fi; \
	remote_dir="$$remote_apps/$$destination_platform/$$package_name"; \
	echo "Deploying $$package_name to $$remote_dir"; \
	ADB_SERIAL="$$serial" PLATFORM_ID="mlp1" \
	REMOTE_SDCARD_PATH="$$remote_sd" \
		"$(LEAF_ROOT)/scripts/adb-stage-app-package.sh" \
		"$$package_dir" "$$remote_dir"

release-zips:
	DEVICE="$(DEVICE)" \
	LEAF_WORKSPACE_DIR="$(WORKSPACE_DIR)" \
	RELEASE_BUILD="$(RELEASE_BUILD)" \
	RELEASE_ID="$(RELEASE_ID)" \
	LEAF_RELEASE_CHANNEL="$(LEAF_RELEASE_CHANNEL)" \
	LEAF_RELEASE_VERSION="$(LEAF_RELEASE_VERSION)" \
	LEAF_RELEASE_TAG="$(LEAF_RELEASE_TAG)" \
	LEAF_RELEASE_REPOSITORY="$(LEAF_RELEASE_REPOSITORY)" \
	STAGE_APPS="$(STAGE_APPS)" \
	STAGE_EMULATORS="$(STAGE_EMULATORS)" \
	PUBLIC_ROOT_DIRS="$(PUBLIC_ROOT_DIRS)" \
	CATASTROPHE_DIR="$(CATASTROPHE_DIR)" \
	JAWAKA_DIR="$(JAWAKA_DIR)" \
	PPSSPP_SPRUCE_DIR="$(PPSSPP_SPRUCE_DIR)" \
	STEWARD_NDS_DIR="$(STEWARD_NDS_DIR)" \
	N64_STANDALONE_DIR="$(N64_STANDALONE_DIR)" \
	FLYCAST_STANDALONE_DIR="$(FLYCAST_STANDALONE_DIR)" \
	YABASANSHIRO_STANDALONE_DIR="$(YABASANSHIRO_STANDALONE_DIR)" \
	RETROARCH_BUILDS_DIR="$(RETROARCH_BUILDS_DIR)" \
	CORES_SPRUCE_DIR="$(CORES_SPRUCE_DIR)" \
	LAUNCHER_SWITCHER_DIR="$(LAUNCHER_SWITCHER_DIR)" \
	TOOLCHAIN_IMAGE="$(TOOLCHAIN_IMAGE)" \
	MLP1_RETROARCH_BIN="$(MLP1_RETROARCH_BIN)" \
	MLP1_RETROARCH_MANIFEST="$(MLP1_RETROARCH_MANIFEST)" \
	MLP1_SHADERS_DIR="$(MLP1_SHADERS_DIR)" \
	MLP1_CORES_DIR="$(MLP1_CORES_DIR)" \
	MLP1_CORES_REPORT="$(MLP1_CORES_REPORT)" \
	REBUILD_CORES="$(REBUILD_CORES)" \
	MLP1_PPSSPP_PACKAGE="$(MLP1_PPSSPP_PACKAGE)" \
	MLP1_GRAPHICS_RUNTIME="$(MLP1_GRAPHICS_RUNTIME)" \
	MLP1_VULKAN_RUNTIME="$(MLP1_VULKAN_RUNTIME)" \
	MLP1_DRASTIC_PACKAGE="$(MLP1_DRASTIC_PACKAGE)" \
	MLP1_MUPEN64PLUS_PACKAGE="$(MLP1_MUPEN64PLUS_PACKAGE)" \
	MLP1_FLYCAST_PACKAGE="$(MLP1_FLYCAST_PACKAGE)" \
	MLP1_YABASANSHIRO_PACKAGE="$(MLP1_YABASANSHIRO_PACKAGE)" \
	MLP1_RETROARCH_PATCH_SET="$(MLP1_RETROARCH_PATCH_SET)" \
	"$(LEAF_ROOT)/scripts/make-sd-release-zip.sh" both

release-sd-zip:
	DEVICE="$(DEVICE)" \
	LEAF_WORKSPACE_DIR="$(WORKSPACE_DIR)" \
	RELEASE_BUILD="$(RELEASE_BUILD)" \
	RELEASE_ID="$(RELEASE_ID)" \
	LEAF_RELEASE_CHANNEL="$(LEAF_RELEASE_CHANNEL)" \
	LEAF_RELEASE_VERSION="$(LEAF_RELEASE_VERSION)" \
	LEAF_RELEASE_TAG="$(LEAF_RELEASE_TAG)" \
	LEAF_RELEASE_REPOSITORY="$(LEAF_RELEASE_REPOSITORY)" \
	STAGE_APPS="$(STAGE_APPS)" \
	STAGE_EMULATORS="$(STAGE_EMULATORS)" \
	PUBLIC_ROOT_DIRS="$(PUBLIC_ROOT_DIRS)" \
	CATASTROPHE_DIR="$(CATASTROPHE_DIR)" \
	JAWAKA_DIR="$(JAWAKA_DIR)" \
	PPSSPP_SPRUCE_DIR="$(PPSSPP_SPRUCE_DIR)" \
	STEWARD_NDS_DIR="$(STEWARD_NDS_DIR)" \
	N64_STANDALONE_DIR="$(N64_STANDALONE_DIR)" \
	FLYCAST_STANDALONE_DIR="$(FLYCAST_STANDALONE_DIR)" \
	YABASANSHIRO_STANDALONE_DIR="$(YABASANSHIRO_STANDALONE_DIR)" \
	RETROARCH_BUILDS_DIR="$(RETROARCH_BUILDS_DIR)" \
	CORES_SPRUCE_DIR="$(CORES_SPRUCE_DIR)" \
	LAUNCHER_SWITCHER_DIR="$(LAUNCHER_SWITCHER_DIR)" \
	TOOLCHAIN_IMAGE="$(TOOLCHAIN_IMAGE)" \
	MLP1_RETROARCH_BIN="$(MLP1_RETROARCH_BIN)" \
	MLP1_RETROARCH_MANIFEST="$(MLP1_RETROARCH_MANIFEST)" \
	MLP1_SHADERS_DIR="$(MLP1_SHADERS_DIR)" \
	MLP1_CORES_DIR="$(MLP1_CORES_DIR)" \
	MLP1_CORES_REPORT="$(MLP1_CORES_REPORT)" \
	REBUILD_CORES="$(REBUILD_CORES)" \
	MLP1_PPSSPP_PACKAGE="$(MLP1_PPSSPP_PACKAGE)" \
	MLP1_GRAPHICS_RUNTIME="$(MLP1_GRAPHICS_RUNTIME)" \
	MLP1_VULKAN_RUNTIME="$(MLP1_VULKAN_RUNTIME)" \
	MLP1_DRASTIC_PACKAGE="$(MLP1_DRASTIC_PACKAGE)" \
	MLP1_MUPEN64PLUS_PACKAGE="$(MLP1_MUPEN64PLUS_PACKAGE)" \
	MLP1_FLYCAST_PACKAGE="$(MLP1_FLYCAST_PACKAGE)" \
	MLP1_YABASANSHIRO_PACKAGE="$(MLP1_YABASANSHIRO_PACKAGE)" \
	MLP1_RETROARCH_PATCH_SET="$(MLP1_RETROARCH_PATCH_SET)" \
	"$(LEAF_ROOT)/scripts/make-sd-release-zip.sh" install

release-recovery-zip:
	DEVICE="$(DEVICE)" \
	LEAF_WORKSPACE_DIR="$(WORKSPACE_DIR)" \
	RELEASE_BUILD="$(RELEASE_BUILD)" \
	RELEASE_ID="$(RELEASE_ID)" \
	LAUNCHER_SWITCHER_DIR="$(LAUNCHER_SWITCHER_DIR)" \
	"$(LEAF_ROOT)/scripts/make-sd-release-zip.sh" recovery

# Build publishable beta ZIPs from one input. RELEASE_ID is the exact artifact
# identity; LEAF_RELEASE_VERSION is the display and compatibility identity;
# LEAF_RELEASE_CHANNEL records beta build/publication policy; LEAF_RELEASE_TAG
# records the GitHub publication reference. Version drops the leading "v".
#
#   make beta-zips TAG=v0.8.0-beta.3 DEVICE=mlp1
#
# TAG is consumed from the recipe environment instead of interpolated into
# shell source. Explicit child-make assignments make the derived identity win
# over conflicting command-line variables inherited through MAKEOVERRIDES.
beta-zips:
	@set -euo pipefail; \
	tag="$${LEAF_BETA_TAG_INPUT:-}"; \
	if [ "$${GITHUB_REF_TYPE:-}" = "tag" ]; then \
		ref_tag="$${GITHUB_REF_NAME:-}"; \
		if [ -z "$$ref_tag" ]; then \
			echo "refusing: GITHUB_REF_TYPE is tag but GITHUB_REF_NAME is empty" >&2; \
			exit 2; \
		fi; \
		if [ -n "$$tag" ] && [ "$$tag" != "$$ref_tag" ]; then \
			echo "refusing: TAG '$$tag' does not match GITHUB_REF_NAME '$$ref_tag'" >&2; \
			exit 2; \
		fi; \
		tag="$$ref_tag"; \
	fi; \
	if [ -z "$$tag" ]; then \
		echo "usage: make beta-zips TAG=v0.8.0-beta.3 [DEVICE=mlp1]" >&2; \
		exit 2; \
	fi; \
	python3 "$(LEAF_ROOT)/scripts/validate-leaf-release.py" beta-tag --tag "$$tag"; \
	version="$${tag#v}"; \
	release_build="$${RELEASE_BUILD:-$(LEAF_ROOT)/build/release}"; \
	echo "==> beta identity: release_id=$$tag tag=$$tag version=$$version channel=beta"; \
	$(MAKE) --no-print-directory release-zips \
		DEVICE=mlp1 \
		TAG="$$tag" \
		RELEASE_BUILD="$$release_build" \
		RELEASE_ID="$$tag" \
		LEAF_RELEASE_CHANNEL=beta \
		LEAF_RELEASE_VERSION="$$version" \
		LEAF_RELEASE_TAG="$$tag" \
		LEAF_RELEASE_REPOSITORY=Utility-Muffin-Research-Kitchen/Leaf-beta; \
	$(MAKE) --no-print-directory verify-beta-zips \
		DEVICE=mlp1 \
		RELEASE_BUILD="$$release_build" \
		TAG="$$tag"

# Read the identity back out of the artifact. Every other check in this repo
# runs on the inputs, which cannot catch a variable that was never set -- an
# unset channel does not fail, it defaults to "dev" and ships.
verify-beta-zips:
	@set -euo pipefail; \
	tag="$${LEAF_BETA_TAG_INPUT:-}"; \
	if [ -z "$$tag" ]; then \
		echo "usage: make verify-beta-zips TAG=v0.8.0-beta.3 [RELEASE_BUILD=...]" >&2; \
		exit 2; \
	fi; \
	release_build="$${RELEASE_BUILD:-$(LEAF_ROOT)/build/release}"; \
	python3 "$(LEAF_ROOT)/scripts/validate-leaf-release.py" beta-tag --tag "$$tag"; \
	python3 "$(LEAF_ROOT)/scripts/verify-release-identity.py" \
		"$$release_build/leaf-mlp1-sd-$$tag.zip" \
		--manifest "$$release_build/leaf-update.json" \
		--repository Utility-Muffin-Research-Kitchen/Leaf-beta \
		--tag "$$tag" \
		--channel beta

# The stable twin of beta-zips. Stable was still four hand-typed env vars after
# betas got a guarded target, which is the wrong way round: a stable mistake
# reaches everyone, not just testers. v0.8.0 was cut by hand for exactly this
# reason. Same contract as beta-zips -- one input, derived identity, verified
# afterwards -- except the tag must be a bare vX.Y.Z and the channel is stable,
# which also arms the clean-worktree provenance gate.
#
#   make stable-zips TAG=v0.9.0 DEVICE=mlp1
#
# TAG is read from the recipe environment rather than interpolated into shell
# source (see the LEAF_BETA_TAG_INPUT capture above), and the derived identity is
# passed explicitly so it beats anything inherited through MAKEOVERRIDES.
stable-zips:
	@set -euo pipefail; \
	tag="$${LEAF_BETA_TAG_INPUT:-}"; \
	if [ "$${GITHUB_REF_TYPE:-}" = "tag" ]; then \
		ref_tag="$${GITHUB_REF_NAME:-}"; \
		if [ -z "$$ref_tag" ]; then \
			echo "refusing: GITHUB_REF_TYPE is tag but GITHUB_REF_NAME is empty" >&2; \
			exit 2; \
		fi; \
		if [ -n "$$tag" ] && [ "$$tag" != "$$ref_tag" ]; then \
			echo "refusing: TAG '$$tag' does not match GITHUB_REF_NAME '$$ref_tag'" >&2; \
			exit 2; \
		fi; \
		tag="$$ref_tag"; \
	fi; \
	if [ -z "$$tag" ]; then \
		echo "usage: make stable-zips TAG=v0.9.0 [DEVICE=mlp1]" >&2; \
		exit 2; \
	fi; \
	python3 "$(LEAF_ROOT)/scripts/validate-leaf-release.py" stable-tag --tag "$$tag"; \
	version="$${tag#v}"; \
	release_build="$${RELEASE_BUILD:-$(LEAF_ROOT)/build/release}"; \
	echo "==> stable identity: release_id=$$tag tag=$$tag version=$$version channel=stable"; \
	$(MAKE) --no-print-directory release-zips \
		DEVICE=mlp1 \
		TAG="$$tag" \
		RELEASE_BUILD="$$release_build" \
		RELEASE_ID="$$tag" \
		LEAF_RELEASE_CHANNEL=stable \
		LEAF_RELEASE_VERSION="$$version" \
		LEAF_RELEASE_TAG="$$tag" \
		LEAF_RELEASE_REPOSITORY=Utility-Muffin-Research-Kitchen/Leaf; \
	$(MAKE) --no-print-directory verify-stable-zips \
		DEVICE=mlp1 \
		RELEASE_BUILD="$$release_build" \
		TAG="$$tag"

verify-stable-zips:
	@set -euo pipefail; \
	tag="$${LEAF_BETA_TAG_INPUT:-}"; \
	if [ -z "$$tag" ]; then \
		echo "usage: make verify-stable-zips TAG=v0.9.0 [RELEASE_BUILD=...]" >&2; \
		exit 2; \
	fi; \
	release_build="$${RELEASE_BUILD:-$(LEAF_ROOT)/build/release}"; \
	python3 "$(LEAF_ROOT)/scripts/validate-leaf-release.py" stable-tag --tag "$$tag"; \
	python3 "$(LEAF_ROOT)/scripts/verify-release-identity.py" \
		"$$release_build/leaf-mlp1-sd-$$tag.zip" \
		--manifest "$$release_build/leaf-update.json" \
		--repository Utility-Muffin-Research-Kitchen/Leaf \
		--tag "$$tag" \
		--channel stable
