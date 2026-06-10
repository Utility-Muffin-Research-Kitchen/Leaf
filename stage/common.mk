# Shared variables for Leaf staging. Included by the top-level Makefile and by
# per-device recipes (stage/<device>.mk).

# Leaf repo root (this file lives in stage/).
LEAF_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)

# Parent workspace root. Override with LEAF_WORKSPACE_DIR for unusual layouts.
WORKSPACE_DIR ?= $(if $(LEAF_WORKSPACE_DIR),$(abspath $(LEAF_WORKSPACE_DIR)),$(abspath $(LEAF_ROOT)/..))

# Compatibility alias for older recipes while Leaf is being split out.
ROOT := $(WORKSPACE_DIR)

# Target device. Selects which stage/<DEVICE>.mk recipe is used.
DEVICE ?= mlp1

# Sibling repo locations (override on the command line if checked out elsewhere).
UMRK_WORKSPACE_DIR     ?= $(WORKSPACE_DIR)/umrk-workspace
CATASTROPHE_DIR        ?= $(WORKSPACE_DIR)/Catastrophe
JAWAKA_DIR             ?= $(WORKSPACE_DIR)/Jawaka
CENTRAL_SCRUTINIZER_DIR ?= $(WORKSPACE_DIR)/CentralScrutinizer
RETROARCH_BUILDS_DIR   ?= $(WORKSPACE_DIR)/retroarch-builds
CORES_SPRUCE_DIR       ?= $(WORKSPACE_DIR)/Cores-spruce
TOOLCHAIN_DIR          ?= $(WORKSPACE_DIR)/mlp1-toolchain
LAUNCHER_SWITCHER_DIR  ?= $(WORKSPACE_DIR)/miniloong-launcher-switcher

# Cross-compile toolchain image (matches miniloong-launcher-switcher's default).
TOOLCHAIN_IMAGE ?= ghcr.io/utility-muffin-research-kitchen/mlp1-toolchain:local

# All sibling repos, used by bootstrap/status.
ALL_REPOS := umrk-workspace Catastrophe Jawaka Thing-File ssh-server CentralScrutinizer Fugazi retroarch-builds \
             Cores-spruce mlp1-toolchain miniloong-launcher-switcher \
             miniloong-adb-keeper
