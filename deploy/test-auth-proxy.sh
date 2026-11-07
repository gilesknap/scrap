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

# kubectl and helm record their calls, in order, in one file; `get secret NAME`
# succeeds only once $tmp/secret-NAME exists.
cat >"$tmp/bin/kubectl" <<STUB
#!/bin/sh
echo "kubectl \$*" >>"$tmp/calls"
case "\$*" in
  *"create secret generic "*) n=\${*#*create secret generic }; touch "$tmp/secret-\${n%% *}"; exit 0 ;;
  *"get secret "*) n=\${*#*get secret }; [ -e "$tmp/secret-\${n%% *}" ]; exit \$? ;;
  *"rollout \${STUB_ROLLOUT_FAIL:-none} "*) exit 1 ;;
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

kc=oauth2-proxy-keycloak
rd=oauth2-proxy-redis
restarts='kubectl -n login rollout restart deploy/oauth2-proxy-redis|kubectl -n login rollout status deploy/oauth2-proxy-redis|kubectl -n login rollout restart deploy/oauth2-proxy|kubectl -n login rollout status deploy/oauth2-proxy|'
# The calls that matter, in order, joined by |.
order() {
    grep -o '^kubectl -n login create secret generic [a-z0-9-]*\|^helm upgrade\|^kubectl -n login rollout [a-z]* deploy/[a-z0-9-]*' "$tmp/calls" |
        tr '\n' '|'
}

# Both Secrets exist: upgrade only, no restart.
touch "$tmp/secret-$kc" "$tmp/secret-$rd"; : >"$tmp/calls"
run </dev/null >"$tmp/out" 2>&1
check "keeps the Secrets" sh -c "grep -q '$kc already exists in login' '$tmp/out' &&
    grep -q '$rd already exists in login' '$tmp/out' && ! grep -q 'create secret' '$tmp/calls'"
check "upgrades the release" grep -q "^helm upgrade --install oauth2-proxy oauth2-proxy .*--namespace login" "$tmp/calls"
check "no restart when the Secrets are kept" sh -c "! grep -q rollout '$tmp/calls'"

# Only the Redis Secret is missing (an upgrade from cookie sessions): it is made with no
# prompt, from a file, then the upgrade, then Redis and the proxy restart.
rm -f "$tmp/secret-$rd"; : >"$tmp/calls"
run </dev/null >"$tmp/out" 2>&1
check "makes the Redis Secret from a file" grep -q "^kubectl -n login create secret generic $rd --from-file=redis-password=" "$tmp/calls"
check "restarts Redis then the proxy after the upgrade" [ "$(order)" = \
    "kubectl -n login create secret generic $rd|helm upgrade|$restarts" ]

# values.yaml uses the Secret install.sh makes, for the proxy and for Redis.
values=$here/dls/auth-proxy/values.yaml
check "values keep sessions in Redis" grep -q '^  type: redis$' "$values"
check "values name the Redis Secret" sh -c "grep -q '^    existingSecret: $rd\$' '$values' &&
    grep -q '^                      name: $rd\$' '$values'"

# A new Secret: made from the answers, then the upgrade, then a restart and its wait.
if command -v script >/dev/null 2>&1 && script -qec true /dev/null </dev/null >/dev/null 2>&1; then
    rm -f "$tmp/secret-"*; : >"$tmp/calls"
    printf 'my-client\nmy-secret\n' |
        PATH="$tmp/bin:$PATH" SCRAP_AUTH_NAMESPACE=login \
            script -qec "sh '$here/dls/auth-proxy/install.sh'" /dev/null >"$tmp/out" 2>&1
    check "makes the Secret" grep -q "^kubectl -n login create secret generic $kc" "$tmp/calls"
    check "secret never on a command line" sh -c "! grep -q my-secret '$tmp/calls'"
    check "makes both Secrets, then restarts Redis and the proxy after the upgrade, and waits" \
        [ "$(order)" = "kubectl -n login create secret generic $kc|kubectl -n login create secret generic $rd|helm upgrade|$restarts" ]

    # The restart, or the wait for it, fails: the script fails and says what to run.
    for step in restart status; do
        rm -f "$tmp/secret-"*; : >"$tmp/calls"
        if printf 'my-client\nmy-secret\n' |
            PATH="$tmp/bin:$PATH" SCRAP_AUTH_NAMESPACE=login STUB_ROLLOUT_FAIL=$step \
                script -qec "sh '$here/dls/auth-proxy/install.sh'" -e /dev/null >"$tmp/out" 2>&1; then
            rc=0
        else rc=1; fi
        check "a failed rollout $step fails the script" [ "$rc" = 1 ]
        check "a failed rollout $step says what to run" sh -c "grep -q 'did not restart' '$tmp/out' &&
            grep -q 'kubectl -n login rollout restart deploy/oauth2-proxy-redis deploy/oauth2-proxy' '$tmp/out'"
    done
else
    echo "skip a new Secret (no script(1) to give the prompts a terminal)"
fi

exit $fail
