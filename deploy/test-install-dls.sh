#!/bin/sh
# Tests for install-dls.sh with stub kubectl/helm (no cluster needed).
# Run: ./deploy/test-install-dls.sh
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

# kubectl: records calls; `get secret` succeeds only once $tmp/secret exists.
cat >"$tmp/bin/kubectl" <<STUB
#!/bin/sh
echo "\$*" >>"$tmp/kubectl.calls"
case "\$*" in
  *"create secret"*) touch "$tmp/secret"; exit 0 ;;
  *"get secret"*ANTHROPIC*) [ -e "$tmp/key" ] && echo eg== ; exit 0 ;;
  *"get secret"*) [ -e "$tmp/secret" ]; exit \$? ;;
  *"config view"*) printf '%s' "\${STUB_NS:-}"; exit 0 ;;
  *"get svc"*loadBalancer*) printf 192.0.2.7; exit 0 ;;
  *"get svc"*) printf 10.1.2.3; exit 0 ;;
esac
exit 0
STUB
cat >"$tmp/bin/helm" <<STUB
#!/bin/sh
echo "\$*" >>"$tmp/helm.calls"
while [ \$# -gt 0 ]; do [ "\$1" = -f ] && cp "\$2" "$tmp/values.yaml"; shift; done
STUB
chmod +x "$tmp/bin/"*

run() { PATH="$tmp/bin:$PATH" USER=hgv27681 "$here/install-dls.sh" </dev/null >"$tmp/out" 2>&1; }

# First run: key from the environment, token generated and shown once.
: >"$tmp/kubectl.calls"; touch "$tmp/key"
ANTHROPIC_API_KEY=sk-test run
check "creates the secret" grep -q "create secret generic scrap-secrets" "$tmp/kubectl.calls"
check "key never on a command line" sh -c "! grep -q sk-test '$tmp/kubectl.calls' '$tmp/helm.calls'"
check "installs pinned version" grep -q -- "--version 1.4.0" "$tmp/helm.calls"
check "namespace falls back to USER" grep -q -- "--namespace hgv27681" "$tmp/helm.calls"
check "host from USER" grep -q "scrap.hgv27681.diamond.ac.uk" "$tmp/values.yaml"
check "ingest enabled" grep -q "enabled: true" "$tmp/values.yaml"
check "token shown" grep -q "bearer token (shown once" "$tmp/out"
check "service ip shown" grep -q "10.1.2.3" "$tmp/out"
check "clusterip by default" grep -q "type: ClusterIP" "$tmp/values.yaml"
check "ticket advice" grep -q "cloud team ticket" "$tmp/out"
check "no network policy by default" sh -c "! grep -q networkPolicy '$tmp/values.yaml'"

# Re-run: the secret exists, so no create and no token printed.
: >"$tmp/kubectl.calls"
run
check "keeps existing secret" sh -c "! grep -q 'create secret' '$tmp/kubectl.calls'"
check "token not reshown" sh -c "! grep -q 'shown once' '$tmp/out'"

SCRAP_SERVICE_TYPE=LoadBalancer run
check "loadbalancer opt-in" grep -q "type: LoadBalancer" "$tmp/values.yaml"
check "external ip shown" grep -q "192.0.2.7" "$tmp/out"

# Options: ingress class, controller namespace, namespace from kubectl context.
STUB_NS=work SCRAP_INGRESS_CLASS=internal SCRAP_INGRESS_NAMESPACE=ingress-nginx run
check "namespace from context" grep -q -- "--namespace work" "$tmp/helm.calls"
check "ingress class" grep -q "className: internal" "$tmp/values.yaml"
check "network policy" grep -q "kubernetes.io/metadata.name: ingress-nginx" "$tmp/values.yaml"

# No secret and no key: ingest off.
rm -f "$tmp/secret" "$tmp/key"
run
check "ingest off without a key" grep -q "enabled: false" "$tmp/values.yaml"

exit $fail
