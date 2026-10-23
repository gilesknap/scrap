#!/bin/sh
# Tests for install.sh with stub systemctl/podman/loginctl (no systemd or podman
# needed). Run: ./deploy/test-install.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
if [ "$(id -u)" = 0 ]; then
    echo "skip: install.sh refuses to run as root"
    exit 0
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0
home="$tmp/home"
mkdir -p "$home" "$tmp/bin" "$tmp/run"

# Stubs: systemctl logs each call; podman knows every image and runs nothing.
cat >"$tmp/bin/systemctl" <<STUB
#!/bin/sh
echo "\$*" >>"$tmp/calls"
case "\$*" in *is-active*) echo inactive; exit 3 ;; esac
exit 0
STUB
cat >"$tmp/bin/loginctl" <<'STUB'
#!/bin/sh
echo yes
STUB
cat >"$tmp/bin/podman" <<STUB
#!/bin/sh
case "\$1 \$2" in "image exists") echo "\$3" >"$tmp/image"; exit 0 ;; esac
case "\$1" in run) exit 1 ;; esac
exit 0
STUB
chmod +x "$tmp/bin/"*

# run_install: install.sh against the stubs, XDG_CONFIG_HOME pointing elsewhere.
run_install() {
    : >"$tmp/calls"
    HOME="$home" XDG_CONFIG_HOME="$tmp/xdg" XDG_RUNTIME_DIR="$tmp/run" \
        PODMAN="$tmp/bin/podman" PATH="$tmp/bin:$PATH" \
        "$here/install.sh" >"$tmp/out" 2>&1
}

check() { # check DESCRIPTION CONDITION-COMMAND...
    desc=$1
    shift
    if "$@"; then echo "ok   $desc"; else echo "FAIL $desc"; fail=1; fi
}

# 75: config lives in ~/.config whatever XDG_CONFIG_HOME says.
run_install || { cat "$tmp/out"; fail=1; }
check "env file in ~/.config/scrap" test -f "$home/.config/scrap/env"
check "unit in ~/.config/systemd/user" test -f "$home/.config/systemd/user/scrap.service"
check "XDG_CONFIG_HOME not used" test ! -e "$tmp/xdg"

# 77: reset-failed runs before the enable --now that the start limit blocks.
# shellcheck disable=SC2016 # $1 is for the inner sh
check "reset-failed before enable --now" sh -c '
    r=$(grep -n "^--user reset-failed scrap.service" "$1" | head -n1 | cut -d: -f1)
    e=$(grep -n "^--user enable --now scrap.service" "$1" | head -n1 | cut -d: -f1)
    [ -n "$r" ] && [ -n "$e" ] && [ "$r" -lt "$e" ]' _ "$tmp/calls"

# 76: a duplicated SCRAP_IMAGE= key: the last one (as systemd reads it) wins.
printf 'SCRAP_IMAGE=localhost/scrap:old\nSCRAP_IMAGE="localhost/scrap:new"\nSCRAP_LISTEN=socket\n' \
    >"$home/.config/scrap/env"
run_install || true
check "last SCRAP_IMAGE wins" test "$(cat "$tmp/image")" = localhost/scrap:new

exit "$fail"
