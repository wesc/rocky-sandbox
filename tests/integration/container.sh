#!/usr/bin/env bash
# The fake docker daemon: runs `docker run ...` in place, as root, through the
# image's real entrypoint. Without privileges it stands in for:
#
#   bind mounts   moves the host directory to the container path for the
#                 container's lifetime, and leaves a symlink behind. A symlink
#                 alone will not do: usermod refuses a symlinked home. Refuses
#                 --mount values with CSV quoting.
#   a fresh /etc  restores /etc/passwd and friends from the snapshot taken
#                 before the tests, at start and at exit.
#   the hostname  sets HOSTNAME only.
#
# It ignores --rm, --init, --interactive, --tty, --publish and --label: stdin
# and stdout are inherited, and nothing else applies here. Moving directories
# means one container per host directory at a time.
set -euo pipefail

IT=/opt/rocky-it

restore_etc() {
    local file
    for file in passwd group shadow gshadow; do
        cp "$IT/etc/$file" "/etc/$file"
    done
}

# Pairs of host path and container path, for every directory moved.
mounted=()

mount_dir() {
    local source="$1" target="$2"
    mv "$source" "$target"
    ln -s "$target" "$source"
    mounted+=("$source" "$target")
}

# shellcheck disable=SC2329 # invoked by the EXIT trap below
unmount_all() {
    local i
    for ((i = ${#mounted[@]} - 2; i >= 0; i -= 2)); do
        rm "${mounted[i]}"
        mv "${mounted[i + 1]}" "${mounted[i]}"
    done
}

# $1 is a --mount value: type=bind,source=...,target=...
bind_mount() {
    local field source="" target=""
    local -a fields
    if [[ "$1" == *'"'* ]]; then
        echo "fake docker run: quoted --mount values are not supported" >&2
        exit 125
    fi
    IFS=, read -ra fields <<< "$1"
    for field in "${fields[@]}"; do
        case "$field" in
            source=*) source="${field#source=}" ;;
            target=*) target="${field#target=}" ;;
        esac
    done
    mount_dir "$source" "$target"
}

restore_etc
trap 'unmount_all; restore_etc' EXIT

# The container's environment: the image's, then docker's own, then --env.
mapfile -t environment < "$IT/image.env"
workdir=/

while [[ $# -gt 0 ]]; do
    case "$1" in
        --rm | --init | --interactive | --tty)
            shift
            ;;
        --publish | --label)
            shift 2
            ;;
        --hostname)
            environment+=("HOSTNAME=$2")
            shift 2
            ;;
        --workdir)
            workdir="$2"
            shift 2
            ;;
        --env)
            environment+=("$2")
            shift 2
            ;;
        --mount)
            bind_mount "$2"
            shift 2
            ;;
        -*)
            echo "fake docker run: unsupported option $1" >&2
            exit 125
            ;;
        *)
            break
            ;;
    esac
done

shift # the image: there is only the one, the image this is running in
if [[ $# -eq 0 ]]; then
    set -- bash # the image's CMD
fi

# Not exec'd, so the EXIT trap moves the directories back.
cd "$workdir"
status=0
env -i "${environment[@]}" /usr/local/bin/rocky-entrypoint "$@" || status=$?
exit "$status"
