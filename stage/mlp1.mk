# MLP1 staging recipes. Included by the top-level Makefile when DEVICE=mlp1.
# Dispatches to each sibling repo's own targets — does not reimplement builds.

# Apps staged by `make stage`.
STAGE_APPS ?= ssh-server Thing-File CentralScrutinizer Fugazi joes-calibrage retroarch-builds
STAGE_EMULATORS ?= ppsspp drastic
PUBLIC_ROOT_DIRS ?= Roms Images Apps BIOS Saves States Cheats

# --- Launcher payload assembly inputs --------------------------------------
JAWAKA_BUILD_DIR ?= $(JAWAKA_DIR)/build/mlp1
DEVICE_OVERLAY   ?= $(LAUNCHER_SWITCHER_DIR)/device/mlp1
CATASTROPHE_ASSETS_DIR ?= $(CATASTROPHE_DIR)/res/assets
MLP1_RETROARCH_BIN ?= $(RETROARCH_BUILDS_DIR)/output/mlp1/bin/retroarch
MLP1_CORES_DIR     ?= $(CORES_SPRUCE_DIR)/output/mlp1/cores
MLP1_INFO_DIR      ?= $(CORES_SPRUCE_DIR)/output/mlp1/info
MLP1_PPSSPP_PACKAGE ?= $(PPSSPP_SPRUCE_DIR)/output/mlp1/ppsspp
MLP1_DRASTIC_PACKAGE ?= $(LEAF_ROOT)/build/drastic/mlp1/drastic
MLP1_RETROARCH_PATCH_SET ?= portrait-rotation,command-menu,jawaka-load-content
UMRK_ENV_SCRIPT    ?= $(LAUNCHER_SWITCHER_DIR)/device/umrk-env.sh
REMOTE_SDCARD_PATH ?= auto
REMOTE_SYSTEM_PATH ?=
REMOTE_PLATFORM_PATH ?=
REMOTE_APPS_PATH ?=

# --- Leaf staging output (gitignored under /build) -------------------------
STAGE_BUILD          ?= $(LEAF_ROOT)/build/stage/mlp1
PAYLOAD_ROOT         := $(STAGE_BUILD)/package
LEAF_SYSTEM_PAYLOAD_DIR := $(PAYLOAD_ROOT)/.system/leaf
PLATFORM_PAYLOAD_DIR := $(LEAF_SYSTEM_PAYLOAD_DIR)/platforms/mlp1
PAYLOAD_DIR          := $(PLATFORM_PAYLOAD_DIR)/launcher

.PHONY: stage stage-app stage-emulator stage-emulators stage-public-root stage-retroarch stage-refresh refresh-jawaka jawaka-build assemble-jawaka stage-jawaka release-zips release-sd-zip release-recovery-zip

# Build the Jawaka MLP1 binaries (cross-compile via its own Docker target).
jawaka-build:
	$(MAKE) -C "$(JAWAKA_DIR)" mlp1

# Assemble the launcher payload tree from Jawaka + Catastrophe + RetroArch +
# cores. Mirrors the former miniloong-launcher-switcher `jawaka-package` target;
# the device overlay still comes from launcher-switcher (device/mlp1 defaults).
assemble-jawaka: jawaka-build
	$(MAKE) -C "$(CATASTROPHE_DIR)" assets
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
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawaka-retroarchctl" "$(PAYLOAD_DIR)/bin/jawaka-retroarchctl"
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawaka-retroarch-runner" "$(PAYLOAD_DIR)/bin/jawaka-retroarch-runner"
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawaka-update-runner" "$(PAYLOAD_DIR)/bin/jawaka-update-runner"
	@cp -f "$(JAWAKA_BUILD_DIR)/bin/jawaka-ledd" "$(PAYLOAD_DIR)/bin/jawaka-ledd"
	@chmod 755 "$(PAYLOAD_DIR)/bin/"*
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
	@mkdir -p "$(PLATFORM_PAYLOAD_DIR)/platform.d"
	@if [ -d "$(JAWAKA_DIR)/platform/mlp1/platform.d" ]; then \
		cp -Rf "$(JAWAKA_DIR)/platform/mlp1/platform.d/." "$(PLATFORM_PAYLOAD_DIR)/platform.d/"; \
		find "$(PLATFORM_PAYLOAD_DIR)/platform.d" -type f -exec chmod 755 {} \;; \
	fi
	@if [ -f "$(MLP1_RETROARCH_BIN)" ]; then \
		mkdir -p "$(PLATFORM_PAYLOAD_DIR)/bin"; \
		cp -f "$(MLP1_RETROARCH_BIN)" "$(PLATFORM_PAYLOAD_DIR)/bin/retroarch"; \
		chmod 755 "$(PLATFORM_PAYLOAD_DIR)/bin/retroarch"; \
	else \
		echo "warning: MLP1 RetroArch not found at $(MLP1_RETROARCH_BIN); launches will fail until built (make stage-retroarch)."; \
	fi
	@if [ -d "$(MLP1_CORES_DIR)" ]; then \
		mkdir -p "$(PLATFORM_PAYLOAD_DIR)/cores"; \
		find "$(MLP1_CORES_DIR)" -maxdepth 1 -type f -name '*_libretro.so' -exec cp -f {} "$(PLATFORM_PAYLOAD_DIR)/cores/" \;; \
		chmod 755 "$(PLATFORM_PAYLOAD_DIR)/cores/"*_libretro.so 2>/dev/null || true; \
	else \
		echo "warning: MLP1 cores not found at $(MLP1_CORES_DIR); launches will fail until built (make stage-retroarch)."; \
	fi
	@if [ -d "$(MLP1_INFO_DIR)" ]; then \
		mkdir -p "$(PLATFORM_PAYLOAD_DIR)/info"; \
		find "$(MLP1_INFO_DIR)" -maxdepth 1 -type f -name '*_libretro.info' -exec cp -f {} "$(PLATFORM_PAYLOAD_DIR)/info/" \;; \
	fi
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
	@if [ ! -f "$(MLP1_RETROARCH_BIN)" ]; then \
		echo "MLP1 RetroArch missing; building in $(RETROARCH_BUILDS_DIR)"; \
		cd "$(RETROARCH_BUILDS_DIR)" && MLP1_PATCH_SET="$(MLP1_RETROARCH_PATCH_SET)" ./build-mlp1.sh; \
	fi
	@if ! ( [ -d "$(MLP1_CORES_DIR)" ] && find "$(MLP1_CORES_DIR)" -maxdepth 1 -type f -name '*_libretro.so' | grep -q . ); then \
		echo "MLP1 cores missing; building in $(CORES_SPRUCE_DIR)"; \
		cd "$(CORES_SPRUCE_DIR)" && ./build-mlp1.sh; \
	fi
	@test -f "$(MLP1_RETROARCH_BIN)" || { echo "missing RetroArch binary: $(MLP1_RETROARCH_BIN)" >&2; exit 1; }
	@test -d "$(MLP1_CORES_DIR)" || { echo "missing cores dir: $(MLP1_CORES_DIR)" >&2; exit 1; }
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
	"$${ADB[@]}" shell "mkdir -p '$$remote_platform' && rm -rf '$$remote_platform/bin' '$$remote_platform/cores' '$$remote_platform/info' && mkdir -p '$$remote_platform/bin' '$$remote_platform/cores' '$$remote_platform/info'"; \
	"$${ADB[@]}" push "$(MLP1_RETROARCH_BIN)" "$$remote_platform/bin/retroarch" >/dev/null; \
	"$${ADB[@]}" push "$(MLP1_CORES_DIR)/." "$$remote_platform/cores/" >/dev/null; \
	if [ -d "$(MLP1_INFO_DIR)" ]; then \
		"$${ADB[@]}" push "$(MLP1_INFO_DIR)/." "$$remote_platform/info/" >/dev/null; \
	fi; \
	"$${ADB[@]}" shell "chmod 755 '$$remote_platform/bin/retroarch' '$$remote_platform/cores/'*_libretro.so 2>/dev/null || true"; \
	"$${ADB[@]}" shell sync; \
	echo "RetroArch platform payload staged."

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
			$(MAKE) -C "$(PPSSPP_SPRUCE_DIR)" package-mlp1; \
			package_dir="$(MLP1_PPSSPP_PACKAGE)"; \
			remote_name="ppsspp"; \
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
	remote_dir="$$remote_platform/emulators/$$remote_name"; \
	echo "Deploying $(EMULATOR) emulator to $$remote_dir"; \
	"$${ADB[@]}" shell "rm -rf \"$$remote_dir\" && mkdir -p \"$$remote_dir\""; \
	"$${ADB[@]}" push "$$package_dir/." "$$remote_dir/" >/dev/null; \
	"$${ADB[@]}" shell "chmod 755 \"$$remote_dir/launch.sh\" \"$$remote_dir/bin/\"* \"$$remote_dir/lib/\"* 2>/dev/null || true"; \
	if [ -d "$(DEVICE_OVERLAY)/defaults" ]; then \
		echo "Refreshing platform defaults at $$remote_platform/defaults"; \
		"$${ADB[@]}" shell "rm -rf '$$remote_platform/defaults' && mkdir -p '$$remote_platform/defaults'"; \
		"$${ADB[@]}" push "$(DEVICE_OVERLAY)/defaults/." "$$remote_platform/defaults/" >/dev/null; \
	fi; \
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
	"$${ADB[@]}" shell "rm -rf \"$$remote_dir\" && mkdir -p \"$$remote_dir\""; \
	"$${ADB[@]}" push "$$package_dir/." "$$remote_dir/" >/dev/null; \
	"$${ADB[@]}" shell "chmod 755 \"$$remote_dir/launch.sh\" \"$$remote_dir/bin/\"* 2>/dev/null || true"; \
	"$${ADB[@]}" shell "find \"$$remote_dir\" -maxdepth 3 -type f | sort"

release-zips:
	DEVICE="$(DEVICE)" \
	LEAF_WORKSPACE_DIR="$(WORKSPACE_DIR)" \
	RELEASE_ID="$(RELEASE_ID)" \
	STAGE_APPS="$(STAGE_APPS)" \
	STAGE_EMULATORS="$(STAGE_EMULATORS)" \
	PUBLIC_ROOT_DIRS="$(PUBLIC_ROOT_DIRS)" \
	CATASTROPHE_DIR="$(CATASTROPHE_DIR)" \
	JAWAKA_DIR="$(JAWAKA_DIR)" \
	PPSSPP_SPRUCE_DIR="$(PPSSPP_SPRUCE_DIR)" \
	STEWARD_NDS_DIR="$(STEWARD_NDS_DIR)" \
	RETROARCH_BUILDS_DIR="$(RETROARCH_BUILDS_DIR)" \
	CORES_SPRUCE_DIR="$(CORES_SPRUCE_DIR)" \
	LAUNCHER_SWITCHER_DIR="$(LAUNCHER_SWITCHER_DIR)" \
	TOOLCHAIN_IMAGE="$(TOOLCHAIN_IMAGE)" \
	MLP1_RETROARCH_BIN="$(MLP1_RETROARCH_BIN)" \
	MLP1_CORES_DIR="$(MLP1_CORES_DIR)" \
	MLP1_PPSSPP_PACKAGE="$(MLP1_PPSSPP_PACKAGE)" \
	MLP1_DRASTIC_PACKAGE="$(MLP1_DRASTIC_PACKAGE)" \
	MLP1_RETROARCH_PATCH_SET="$(MLP1_RETROARCH_PATCH_SET)" \
	"$(LEAF_ROOT)/scripts/make-sd-release-zip.sh" both

release-sd-zip:
	DEVICE="$(DEVICE)" \
	LEAF_WORKSPACE_DIR="$(WORKSPACE_DIR)" \
	RELEASE_ID="$(RELEASE_ID)" \
	STAGE_APPS="$(STAGE_APPS)" \
	STAGE_EMULATORS="$(STAGE_EMULATORS)" \
	PUBLIC_ROOT_DIRS="$(PUBLIC_ROOT_DIRS)" \
	CATASTROPHE_DIR="$(CATASTROPHE_DIR)" \
	JAWAKA_DIR="$(JAWAKA_DIR)" \
	PPSSPP_SPRUCE_DIR="$(PPSSPP_SPRUCE_DIR)" \
	STEWARD_NDS_DIR="$(STEWARD_NDS_DIR)" \
	RETROARCH_BUILDS_DIR="$(RETROARCH_BUILDS_DIR)" \
	CORES_SPRUCE_DIR="$(CORES_SPRUCE_DIR)" \
	LAUNCHER_SWITCHER_DIR="$(LAUNCHER_SWITCHER_DIR)" \
	TOOLCHAIN_IMAGE="$(TOOLCHAIN_IMAGE)" \
	MLP1_RETROARCH_BIN="$(MLP1_RETROARCH_BIN)" \
	MLP1_CORES_DIR="$(MLP1_CORES_DIR)" \
	MLP1_PPSSPP_PACKAGE="$(MLP1_PPSSPP_PACKAGE)" \
	MLP1_DRASTIC_PACKAGE="$(MLP1_DRASTIC_PACKAGE)" \
	MLP1_RETROARCH_PATCH_SET="$(MLP1_RETROARCH_PATCH_SET)" \
	"$(LEAF_ROOT)/scripts/make-sd-release-zip.sh" install

release-recovery-zip:
	DEVICE="$(DEVICE)" \
	LEAF_WORKSPACE_DIR="$(WORKSPACE_DIR)" \
	RELEASE_ID="$(RELEASE_ID)" \
	LAUNCHER_SWITCHER_DIR="$(LAUNCHER_SWITCHER_DIR)" \
	"$(LEAF_ROOT)/scripts/make-sd-release-zip.sh" recovery
