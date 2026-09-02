# Leaf workspace — central command surface.
#
# This Makefile is a DISPATCHER over each sibling repo's own build/package/stage
# targets. It does not reimplement product builds. See README.md for setup.

SHELL := /bin/bash

include stage/common.mk

# Per-device staging recipes (stage-jawaka, stage-app, stage-retroarch, stage).
# Optional so bootstrap/doctor/status work before a device recipe exists.
-include stage/$(DEVICE).mk

LARGE_LIBRARY_FIXTURE_ENV = \
	COUNT="$(if $(COUNT),$(COUNT),1200)" \
	SMALL_COUNT="$(if $(SMALL_COUNT),$(SMALL_COUNT),10)" \
	LARGE_SYSTEMS="$(if $(LARGE_SYSTEMS),$(LARGE_SYSTEMS),FC:nes,SFC:sfc)" \
	SMALL_SYSTEMS="$(if $(SMALL_SYSTEMS),$(SMALL_SYSTEMS),GB:gb)" \
	IMAGE_EVERY="$(if $(IMAGE_EVERY),$(IMAGE_EVERY),0)" \
	FORCE="$(if $(FORCE),$(FORCE),0)" \
	DEVICE="$(DEVICE)" \
	REMOTE_SDCARD_PATH="$(REMOTE_SDCARD_PATH)"

.DEFAULT_GOAL := help
.PHONY: help bootstrap doctor status status-internal pakrat-local-feed-test leaf-release-policy-test shader-bundle-release-policy-test input-roster-policy-test flycast-release-policy-smoke yabasanshiro-release-policy-smoke yabasanshiro-stage-policy-smoke fun-drastic-release-policy-smoke fun-drastic-stage-policy-smoke core-rebuild-gate-test package-quiesce-smoke adb-enable-marker adb-disable-marker adb-tail-logs adb-large-library-create adb-large-library-clean adb-large-library-status adb-install-wrapper adb-uninstall-wrapper benchmark-ppsspp

help:
	@echo "Leaf workspace commands (DEVICE=$(DEVICE), WORKSPACE_DIR=$(WORKSPACE_DIR)):"
	@echo "  make bootstrap                            clone public repos; privately clone internal docs when accessible"
	@echo "  make doctor                               preflight: adb / docker / toolchain / device"
	@echo "  make status                               git status across public siblings"
	@echo "  make status-internal                      git status including private maintainer repos"
	@echo "  make stage DEVICE=mlp1                    full: launcher payload + all apps"
	@echo "  make stage-refresh DEVICE=mlp1            full stage, then run refresh helper"
	@echo "  make refresh-jawaka DEVICE=mlp1           refresh helper (reboot advised with init hook)"
	@echo "  make stage-jawaka DEVICE=mlp1             launcher payload only"
	@echo "  make stage-retroarch DEVICE=mlp1          RetroArch binary + cores + info + shaders"
	@echo "  make stage-core-test CORE=np2kai DEVICE=mlp1  testing only: stage one checksum-verified core"
	@echo "  make stage-emulator EMULATOR=ppsspp DEVICE=mlp1 stage a standalone emulator"
	@echo "  make stage-emulator EMULATOR=drastic DEVICE=mlp1 stage DraStic"
	@echo "  make stage-emulator EMULATOR=mupen64plus DEVICE=mlp1 stage standalone N64"
	@echo "  make stage-emulator EMULATOR=flycast DEVICE=mlp1 stage standalone Dreamcast"
	@echo "  make stage-emulator EMULATOR=yabasanshiro DEVICE=mlp1 stage standalone Saturn"
	@echo "  make stage-emulator EMULATOR=fun-drastic DEVICE=mlp1 FUN_DRASTIC_ARCHIVE=... stage Fun DraStic"
	@echo "  make stage-emulators DEVICE=mlp1          stage standalone emulators"
	@echo "  make stage-app APP=CentralScrutinizer DEVICE=mlp1 stage a single app repo"
	@echo "  make stage-app APP=Leaf-Itchio-Pak DEVICE=mlp1 explicitly stage the optional Itch.io app"
	@echo "  make stage-app APP=Leaf-Syncthing-Pak DEVICE=mlp1 explicitly stage the optional Syncthing app"
	@echo "  make stage-app APP=Leaf-RAOfflineProxy-Pak DEVICE=mlp1 explicitly stage the optional RAOfflineProxy app"
	@echo "  make stage-app APP=DiscoBoy DEVICE=mlp1 explicitly stage the optional Disco Boy app"
	@echo "  make stage-app APP=VideoFromHell DEVICE=mlp1 explicitly stage the optional Video From Hell app"
	@echo "  make stage-app APP=Nimbus DEVICE=mlp1       explicitly stage the optional Nimbus app"
	@echo "  make stage-app APP=PortMaster-mlp1 DEVICE=mlp1 explicitly stage the optional PortMaster app"
	@echo "  make stage-app APP=ScummVM-pak DEVICE=mlp1 explicitly stage the reference content pak"
	@echo "  make release-zips DEVICE=mlp1             build end-user install + recovery ZIPs"
	@echo "    REBUILD_CORES=1                         explicitly permit compiling missing/stale cores"
	@echo "    FORCE_REBUILD_CORES=1                   with REBUILD_CORES=1, bypass every valid cache hit"
	@echo "  make beta-zips TAG=v0.8.0-beta.3 DEVICE=mlp1  build clean beta ZIPs from one tag, then verify"
	@echo "  make stable-zips TAG=v0.10.0 DEVICE=mlp1      build clean stable ZIPs from one tag, then verify"
	@echo "  make release-sd-zip DEVICE=mlp1           build end-user install ZIP"
	@echo "  make release-recovery-zip DEVICE=mlp1     build end-user recovery ZIP"
	@echo "  make pakrat-local-feed-test               test multi-app and exact-artifact local feeds"
	@echo "  make leaf-release-policy-test             test release identity, artifacts, provenance, and gates"
	@echo "  make shader-bundle-release-policy-test    test shader bundle integrity release gates"
	@echo "  make input-roster-policy-test             test the MLP1 paired-controller input gates"
	@echo "  make flycast-release-policy-smoke         test standalone Flycast release gates"
	@echo "  make yabasanshiro-release-policy-smoke    test standalone Saturn release gates"
	@echo "  make yabasanshiro-stage-policy-smoke      test standalone Saturn dispatch"
	@echo "  make fun-drastic-release-policy-smoke fun-drastic-stage-policy-smoke     test the second NDS emulator release gates"
	@echo "  make core-rebuild-gate-test               test explicit long core-rebuild authorization"
	@echo "  make package-quiesce-smoke                test fail-closed stage-app service barrier"
	@echo "  make adb-enable-marker                    enable Leaf launcher marker"
	@echo "  make adb-disable-marker                   disable Leaf launcher marker"
	@echo "  make adb-tail-logs                        tail launcher logs"
	@echo "  make adb-large-library-create             seed fake large-library ROM fixture"
	@echo "  make adb-large-library-status             show fixture and library.db counts"
	@echo "  make adb-large-library-clean              remove fake large-library fixture"
	@echo "  make adb-install-wrapper                  install Leaf init hook (compat alias)"
	@echo "  make adb-uninstall-wrapper                remove Leaf init hook (compat alias)"
	@echo "  make benchmark-ppsspp ROM=/path CORE=vulkan PRESET=balanced TRACE=scripts/ppsspp-input-traces/example.json"

bootstrap:
	@LEAF_WORKSPACE_DIR="$(WORKSPACE_DIR)" scripts/bootstrap.sh $(REQUIRED_REPOS) --optional $(OPTIONAL_PRIVATE_REPOS) $(OPTIONAL_EXAMPLE_REPOS)

flycast-release-policy-smoke:
	@python3 scripts/validate-flycast-standalone-release-test.py

yabasanshiro-release-policy-smoke:
	@python3 scripts/validate-yabasanshiro-standalone-release-test.py

yabasanshiro-stage-policy-smoke:
	@bash scripts/yabasanshiro-stage-policy-smoke.sh

fun-drastic-release-policy-smoke:
	@python3 scripts/validate-fun-drastic-release-test.py

fun-drastic-stage-policy-smoke:
	@bash scripts/fun-drastic-stage-policy-smoke.sh

doctor:
	@LEAF_WORKSPACE_DIR="$(WORKSPACE_DIR)" TOOLCHAIN_IMAGE="$(TOOLCHAIN_IMAGE)" scripts/doctor.sh

status:
	@for r in $(REQUIRED_REPOS); do \
		d="$(WORKSPACE_DIR)/$$r"; \
		if [ -d "$$d/.git" ]; then \
			b="$$(git -C "$$d" rev-parse --abbrev-ref HEAD 2>/dev/null)"; \
			s="$$(git -C "$$d" status --short 2>/dev/null)"; \
			if [ -n "$$s" ]; then state="dirty"; else state="clean"; fi; \
			printf "%-30s %-20s %s\n" "$$r" "$$b" "$$state"; \
		else \
			printf "%-30s %s\n" "$$r" "(missing — run: make bootstrap)"; \
		fi; \
	done

status-internal:
	@for r in $(REQUIRED_REPOS) $(OPTIONAL_PRIVATE_REPOS); do \
		d="$(WORKSPACE_DIR)/$$r"; \
		if [ -d "$$d/.git" ]; then \
			b="$$(git -C "$$d" rev-parse --abbrev-ref HEAD 2>/dev/null)"; \
			s="$$(git -C "$$d" status --short 2>/dev/null)"; \
			if [ -n "$$s" ]; then state="dirty"; else state="clean"; fi; \
			printf "%-30s %-20s %s\n" "$$r" "$$b" "$$state"; \
		else \
			printf "%-30s %s\n" "$$r" "(missing — run: make bootstrap)"; \
		fi; \
	done

pakrat-local-feed-test:
	python3 scripts/pakrat-local-feed-test.py

leaf-release-policy-test:
	python3 scripts/validate-leaf-release-test.py
	python3 scripts/verify-release-identity-test.py

shader-bundle-release-policy-test:
	python3 scripts/validate-shader-bundle-release-test.py

input-roster-policy-test:
	python3 scripts/validate-input-roster-policy-test.py

core-rebuild-gate-test:
	bash scripts/ensure-mlp1-cores-test.sh

package-quiesce-smoke:
	@bash scripts/adb-stage-app-package-smoke.sh

adb-enable-marker:
	scripts/adb-set-marker.sh on

adb-disable-marker:
	scripts/adb-set-marker.sh off

adb-tail-logs:
	scripts/adb-tail-logs.sh

adb-large-library-create:
	$(LARGE_LIBRARY_FIXTURE_ENV) scripts/adb-large-library-fixture.sh create

adb-large-library-status:
	$(LARGE_LIBRARY_FIXTURE_ENV) scripts/adb-large-library-fixture.sh status

adb-large-library-clean:
	$(LARGE_LIBRARY_FIXTURE_ENV) scripts/adb-large-library-fixture.sh clean

adb-install-wrapper:
	scripts/adb-install-wrapper.sh

adb-uninstall-wrapper:
	scripts/adb-uninstall-wrapper.sh

benchmark-ppsspp:
	@test -n "$(ROM)" || { echo "usage: make benchmark-ppsspp ROM=/device/path [CORE=vulkan|gles] [PRESET=balanced|performance] [TRACE=/local/trace.json] [BENCHMARK_ARGS='...']" >&2; exit 1; }
	scripts/ppsspp-benchmark.py \
		--rom "$(ROM)" \
		--core "$(if $(CORE),$(CORE),vulkan)" \
		--preset "$(if $(PRESET),$(PRESET),balanced)" \
		$(if $(TRACE),--input-trace "$(TRACE)") \
		$(BENCHMARK_ARGS)
