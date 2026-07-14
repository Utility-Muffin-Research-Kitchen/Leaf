#!/usr/bin/env bash
# Leaf app package policy. Source this file, then call:
#   leaf_app_policy <repo> <workspace_root> [device]
#
# Outputs globals:
#   package_target
#   package_platform
#   package_dir
#   package_name
#   destination_platform
#   supported_devices
#   distribution      release | pakrat

leaf_known_platform() {
    case "${1:-}" in
        mlp1|tg5040|tg5050|my355|mac|shared) return 0 ;;
        *) return 1 ;;
    esac
}

leaf_pakrat_owned_package_names() {
    printf '%s\n' \
        "Itch-io.pak" \
        "DiscoBoy.pak" \
        "Nimbus.pak" \
        "PortMaster.pak"
}

leaf_app_policy() {
    local app="${1:-}"
    local workspace_dir="${2:-}"
    local device="${3:-}"

    package_target=
    package_platform=
    package_dir=
    package_name=
    destination_platform=
    supported_devices=
    distribution=

    case "$app" in
        Leaf-Itchio-Pak)
            package_target="package-platform"
            package_platform="mlp1"
            package_dir="$workspace_dir/Leaf-Itchio-Pak/build/mlp1/package/Itch-io.pak"
            package_name="Itch-io.pak"
            destination_platform="mlp1"
            supported_devices="mlp1"
            distribution="pakrat"
            ;;
        DiscoBoy)
            package_target="package-platform"
            package_platform="mlp1"
            package_dir="$workspace_dir/DiscoBoy/build/mlp1/package/DiscoBoy.pak"
            package_name="DiscoBoy.pak"
            destination_platform="mlp1"
            supported_devices="mlp1"
            distribution="pakrat"
            ;;
        Nimbus)
            package_target="package-platform"
            package_platform="mlp1"
            package_dir="$workspace_dir/Nimbus/build/mlp1/package/Nimbus.pak"
            package_name="Nimbus.pak"
            destination_platform="mlp1"
            supported_devices="mlp1"
            distribution="pakrat"
            ;;
        PortMaster-mlp1)
            package_target="package-platform"
            package_platform="mlp1"
            package_dir="$workspace_dir/PortMaster-mlp1/build/mlp1/package/PortMaster.pak"
            package_name="PortMaster.pak"
            destination_platform="mlp1"
            supported_devices="mlp1"
            distribution="pakrat"
            ;;
        ssh-server)
            package_target="package-platform"
            package_platform="mlp1"
            package_dir="$workspace_dir/ssh-server/build/mlp1/package/SSHServer.pak"
            package_name="SSHServer.pak"
            destination_platform="mlp1"
            supported_devices="mlp1"
            distribution="release"
            ;;
        Thing-File)
            package_target="package-platform"
            package_platform="mlp1"
            package_dir="$workspace_dir/Thing-File/build/mlp1/package/Thing-File.pak"
            package_name="Thing-File.pak"
            destination_platform="mlp1"
            supported_devices="mlp1"
            distribution="release"
            ;;
        CentralScrutinizer)
            package_target="package-platform"
            package_platform="mlp1"
            package_dir="$workspace_dir/CentralScrutinizer/build/mlp1/package/CentralScrutinizer.pak"
            package_name="CentralScrutinizer.pak"
            destination_platform="mlp1"
            supported_devices="mlp1"
            distribution="release"
            ;;
        Fugazi)
            package_target="package-platform"
            package_platform="mlp1"
            package_dir="$workspace_dir/Fugazi/build/mlp1/package/Fugazi.pak"
            package_name="Fugazi.pak"
            destination_platform="mlp1"
            supported_devices="mlp1"
            distribution="release"
            ;;
        joes-calibrage)
            package_target="package-platform"
            package_platform="mlp1"
            package_dir="$workspace_dir/joes-calibrage/build/mlp1/package/Joe's Calibrage.pak"
            package_name="Joe's Calibrage.pak"
            destination_platform="mlp1"
            supported_devices="mlp1"
            distribution="release"
            ;;
        retroarch-builds)
            package_target="package-platform"
            package_platform="mlp1"
            package_dir="$workspace_dir/retroarch-builds/build/package/RetroArch.pak"
            package_name="RetroArch.pak"
            destination_platform="shared"
            supported_devices="mlp1"
            distribution="release"
            ;;
        *)
            return 1
            ;;
    esac

    leaf_known_platform "$destination_platform" || return 1
    if [ -n "$package_platform" ]; then
        leaf_known_platform "$package_platform" || return 1
    fi
    case "$distribution" in
        release|pakrat) ;;
        *) return 1 ;;
    esac

    if [ -n "$device" ]; then
        leaf_known_platform "$device" || return 2
        case " $supported_devices " in
            *" $device "*) ;;
            *) return 2 ;;
        esac
    fi

    return 0
}
