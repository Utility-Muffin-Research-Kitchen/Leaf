# Leaf workspace — central command surface.
#
# This Makefile is a DISPATCHER over each sibling repo's own build/package/stage
# targets. It does not reimplement product builds. See README.md for setup.

SHELL := /bin/bash

include stage/common.mk

# Per-device staging recipes (stage-jawaka, stage-app, stage-retroarch, stage).
# Optional so bootstrap/doctor/status work before a device recipe exists.
-include stage/$(DEVICE).mk

.DEFAULT_GOAL := help
.PHONY: help bootstrap doctor status adb-enable-marker adb-disable-marker adb-tail-logs adb-install-wrapper adb-uninstall-wrapper

help:
	@echo "Leaf workspace commands (DEVICE=$(DEVICE), WORKSPACE_DIR=$(WORKSPACE_DIR)):"
	@echo "  make bootstrap                            clone any missing sibling repos"
	@echo "  make doctor                               preflight: adb / docker / toolchain / device"
	@echo "  make status                               git status across all siblings"
	@echo "  make stage DEVICE=mlp1                    full: launcher payload + all apps"
	@echo "  make stage-refresh DEVICE=mlp1            full stage, then run refresh helper"
	@echo "  make refresh-jawaka DEVICE=mlp1           refresh helper (reboot advised with init hook)"
	@echo "  make stage-jawaka DEVICE=mlp1             launcher payload only"
	@echo "  make stage-retroarch DEVICE=mlp1          RetroArch binary + cores + info"
	@echo "  make stage-app APP=ssh-server DEVICE=mlp1 stage a single app repo"
	@echo "  make release-zips DEVICE=mlp1             build end-user install + recovery ZIPs"
	@echo "  make release-sd-zip DEVICE=mlp1           build end-user install ZIP"
	@echo "  make release-recovery-zip DEVICE=mlp1     build end-user recovery ZIP"
	@echo "  make adb-enable-marker                    enable Leaf launcher marker"
	@echo "  make adb-disable-marker                   disable Leaf launcher marker"
	@echo "  make adb-tail-logs                        tail launcher logs"
	@echo "  make adb-install-wrapper                  install Leaf init hook (compat alias)"
	@echo "  make adb-uninstall-wrapper                remove Leaf init hook (compat alias)"

bootstrap:
	@LEAF_WORKSPACE_DIR="$(WORKSPACE_DIR)" scripts/bootstrap.sh $(ALL_REPOS)

doctor:
	@LEAF_WORKSPACE_DIR="$(WORKSPACE_DIR)" TOOLCHAIN_IMAGE="$(TOOLCHAIN_IMAGE)" scripts/doctor.sh

status:
	@for r in $(ALL_REPOS); do \
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

adb-enable-marker:
	scripts/adb-set-marker.sh on

adb-disable-marker:
	scripts/adb-set-marker.sh off

adb-tail-logs:
	scripts/adb-tail-logs.sh

adb-install-wrapper:
	scripts/adb-install-wrapper.sh

adb-uninstall-wrapper:
	scripts/adb-uninstall-wrapper.sh
