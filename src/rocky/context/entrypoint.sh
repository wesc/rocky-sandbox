#!/usr/bin/env bash
# Runs as root. Gives the container's `rocky` user the caller's uid and gid,
# seeds a new profile home, then runs the command as the caller.
set -euo pipefail

CONTAINER_USER=rocky
CALLER_UID="${ROCKY_UID:-1000}"
CALLER_GID="${ROCKY_GID:-1000}"

# The PATH an interactive bash gets, as the user that "$@" runs as. Debian's
# ~/.bashrc returns early for a non-interactive shell, and installers add their
# PATH lines below that check, so `rocky run pi-acp` would miss them.
#
# The shell must not touch the command's stdin or stdout, which for an ACP
# adapter carry the protocol: setsid keeps it off the terminal, it reads
# /dev/null, and its output is discarded. It writes PATH to a file, so timeout
# can kill it even if something it started keeps running.
interactive_shell_path() {
    local path_file
    path_file="$(mktemp)"
    chown "$CALLER_UID:$CALLER_GID" "$path_file"
    # KILL: an interactive bash ignores TERM.
    # shellcheck disable=SC2016 # $PATH is for the inner shell to expand
    timeout -s KILL 10 setsid "$@" bash -ic 'printf "%s" "$PATH" > "$1"' rocky "$path_file" \
        >/dev/null 2>&1 </dev/null || true
    cat "$path_file"
    rm -f "$path_file"
}

if [[ "$CALLER_UID" == "0" ]]; then
    as_caller=()
else
    # -o allows an id another account has. macOS puts every user in gid 20,
    # which Debian gives to dialout.
    if [[ "$CALLER_GID" != "$(id -g "$CONTAINER_USER")" ]]; then
        groupmod -o -g "$CALLER_GID" "$CONTAINER_USER"
    fi
    # usermod also chowns the files in the home that the old uid owns. A home
    # from an earlier run has none.
    if [[ "$CALLER_UID" != "$(id -u "$CONTAINER_USER")" ]]; then
        usermod -o -u "$CALLER_UID" "$CONTAINER_USER"
    fi
    as_caller=(setpriv --reuid="$CALLER_UID" --regid="$CALLER_GID" --init-groups --)
    export USER="$CONTAINER_USER"
    export LOGNAME="$CONTAINER_USER"
fi

home="$(getent passwd "$CONTAINER_USER" | cut -d: -f6)"
mkdir -p "$home"

# The mount hides the skeleton home useradd made. An empty home is a new
# profile.
if [[ -z "$(ls -A "$home" 2>/dev/null || true)" ]]; then
    cp -a /opt/rocky-skel/. "$home/"
    chown -R "$CALLER_UID:$CALLER_GID" "$home"
fi
chown "$CALLER_UID:$CALLER_GID" "$home"
export HOME="$home"

if path="$(interactive_shell_path "${as_caller[@]}")" && [[ -n "$path" ]]; then
    export PATH="$path"
fi

exec "${as_caller[@]}" "$@"
