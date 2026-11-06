#!/bin/sh
# Tests for dls/auth-proxy/install.sh with stub kubectl/helm (no cluster needed). The
# first run's prompts read /dev/tty, so that case runs under script(1), which gives it
# a terminal; it is skipped where script is missing.
# Run: ./deploy/test-auth-proxy.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
fail=0
check() { # check NAME CONDITION-COMMAND...
    name=$1; shift
    if "$@"; then echo "ok   $name"; else echo "FAIL $name"; fail=1; fi
}

# kubectl and helm record their calls, in order, in one file; `get secret` succeeds
# only once $tmp/secret exists.
cat >"$tmp/bin/kubectl" <<STUB
#!/bin/sh
echo "kubectl \$*" >>"$tmp/calls"
case "\$*" in
  *"create secret"*) touch "$tmp/secret"; exit 0 ;;
  *"get secret"*) [ -e "$tmp/secret" ]; exit \$? ;;
esac
exit 0
STUB
cat >"$tmp/bin/helm" <<STUB
#!/bin/sh
echo "helm \$*" >>"$tmp/calls"
STUB
chmod +x "$tmp/bin/"*
run() {
    PATH="$tmp/bin:$PATH" SCRAP_AUTH_NAMESPACE=login sh "$here/dls/auth-proxy/install.sh"
}

# The Secret exists: upgrade only, no restart.
touch "$tmp/secret"; : >"$tmp/calls"
run </dev/null >"$tmp/out" 2>&1
check "keeps the Secret" sh -c "grep -q 'already exists in login' '$tmp/out' && ! grep -q 'create secret' '$tmp/calls'"
check "upgrades the release" grep -q "^helm upgrade --install oauth2-proxy oauth2-proxy .*--namespace login" "$tmp/calls"
check "no restart when the Secret is kept" sh -c "! grep -q rollout '$tmp/calls'"

# A new Secret: made from the answers, then the upgrade, then a restart and its wait.
if command -v script >/dev/null 2>&1 && script -qec true /dev/null </dev/null >/dev/null 2>&1; then
    rm -f "$tmp/secret"; : >"$tmp/calls"
    printf 'my-client\nmy-secret\n' |
        PATH="$tmp/bin:$PATH" SCRAP_AUTH_NAMESPACE=login \
            script -qec "sh '$here/dls/auth-proxy/install.sh'" /dev/null >"$tmp/out" 2>&1
    check "makes the Secret" grep -q "^kubectl -n login create secret generic oauth2-proxy-keycloak" "$tmp/calls"
    check "secret never on a command line" sh -c "! grep -q my-secret '$tmp/calls'"
    order=$(grep -o '^kubectl -n login create secret\|^helm upgrade\|^kubectl -n login rollout restart deploy/oauth2-proxy\|^kubectl -n login rollout status deploy/oauth2-proxy' "$tmp/calls" |
        tr '\n' '|')
    check "restarts the proxy after the upgrade, and waits" [ "$order" = \
        "kubectl -n login create secret|helm upgrade|kubectl -n login rollout restart deploy/oauth2-proxy|kubectl -n login rollout status deploy/oauth2-proxy|" ]
else
    echo "skip a new Secret (no script(1) to give the prompts a terminal)"
fi

exit $fail
