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
  *"get secret"*SCRAP_MCP_TOKEN*) [ -e "$tmp/notoken" ] || echo dA== ; exit 0 ;;
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
case "\$*" in
  *" list "*) echo '[{"name":"scrap","chart":"scrap-9.8.7","app_version":"9.8.7"}]'; exit 0 ;;
esac
while [ \$# -gt 0 ]; do [ "\$1" = -f ] && cp "\$2" "$tmp/values.yaml"; shift; done
[ -z "\${STUB_HELM_FAIL:-}" ]
STUB
chmod +x "$tmp/bin/"*

# A key in the developer's shell must not reach the cases that run without one.
unset ANTHROPIC_API_KEY
# Detached from any terminal, so the key prompt cannot open /dev/tty and wait.
detached() {
    if setsid -w true 2>/dev/null; then setsid -w "$@"; else "$@"; fi
}
run() {
    mkdir -p "$tmp/installer-tmp"
    PATH="$tmp/bin:$PATH" USER=hgv27681 SCRAP_BACKUP_DIR="${SCRAP_BACKUP_DIR-$tmp/science/scrap}" \
        TMPDIR="$tmp/installer-tmp" detached "$here/install-dls.sh" </dev/null >"$tmp/out" 2>&1
}

# First run: key from the environment, token generated and shown once.
: >"$tmp/kubectl.calls"; touch "$tmp/key"
(ANTHROPIC_API_KEY=sk-test run)
check "creates the secret" grep -q "create secret generic scrap-secrets" "$tmp/kubectl.calls"
check "key's temp files removed" sh -c "[ -z \"\$(ls -A '$tmp/installer-tmp')\" ]"
check "key never on a command line" sh -c "! grep -q sk-test '$tmp/kubectl.calls' '$tmp/helm.calls'"
check "latest release by default" sh -c "! grep -q -- '--version' '$tmp/helm.calls'"
check "says it installs the latest" sh -c "head -n1 '$tmp/out' | grep -q 'Installing the latest scrap'"
check "prints the installed version" grep -q "scrap 9.8.7 is running" "$tmp/out"
check "namespace falls back to USER" grep -q -- "--namespace hgv27681" "$tmp/helm.calls"
check "host from USER" grep -q "scrap-hgv27681.diamond.ac.uk" "$tmp/values.yaml"
check "nginx class by default" grep -q "className: nginx" "$tmp/values.yaml"
check "tls for the host" grep -A2 -q "tls:" "$tmp/values.yaml"
check "ingest enabled" sh -c "grep -A1 '^ingest:' '$tmp/values.yaml' | grep -q 'enabled: true'"
check "token shown" grep -q "bearer token (shown once" "$tmp/out"
check "service ip shown" grep -q "10.1.2.3" "$tmp/out"
check "clusterip by default" grep -q "type: ClusterIP" "$tmp/values.yaml"
check "ticket advice" grep -q "jira.diamond.ac.uk/servicedesk/customer/portal/2/create/156" "$tmp/out"
check "backup dir made, mode 700" sh -c "[ \"\$(stat -c %a '$tmp/science/scrap')\" = 700 ]"
check "backups on the host path" grep -q "hostPath: $tmp/science/scrap" "$tmp/values.yaml"
check "job cpu limits fit argus" [ "$(grep -c 'limits: {cpu: 500m}' "$tmp/values.yaml")" = 4 ]
check "runs as the user" grep -q "runAsUser: $(id -u)" "$tmp/values.yaml"
check "no network policy" sh -c "! grep -q networkPolicy '$tmp/values.yaml'"

# SCRAP_VERSION picks the release.
: >"$tmp/helm.calls"
(SCRAP_VERSION=1.5.0 run)
check "SCRAP_VERSION passed to helm" grep -q -- "--version 1.5.0" "$tmp/helm.calls"
check "says which version" sh -c "head -n1 '$tmp/out' | grep -q 'Installing scrap 1.5.0 into'"

# Re-run: the secret exists, so no create and no token printed.
: >"$tmp/kubectl.calls"
run
check "keeps existing secret" sh -c "! grep -q 'create secret' '$tmp/kubectl.calls'"
check "token not reshown" sh -c "! grep -q 'shown once' '$tmp/out'"

(SCRAP_SERVICE_TYPE=LoadBalancer run)
check "loadbalancer opt-in" grep -q "type: LoadBalancer" "$tmp/values.yaml"
check "external ip shown" grep -q "192.0.2.7" "$tmp/out"

# Options: ingress class, namespace from kubectl context, plain http.
(STUB_NS=work SCRAP_INGRESS_CLASS=internal SCRAP_SCHEME=http run)
check "namespace from context" grep -q -- "--namespace work" "$tmp/helm.calls"
check "http in the first line" sh -c "head -n1 '$tmp/out' | grep -q 'for http://scrap-'"
check "ingress class" grep -q "className: internal" "$tmp/values.yaml"
check "no tls over http" sh -c "! grep -q 'tls:' '$tmp/values.yaml'"

# A host that already resolves needs no ticket.
(SCRAP_HOST=localhost run)
check "no ticket when the name resolves" sh -c "! grep -q 'servicedesk' '$tmp/out'"

# Helm fails on the first run: the new token is still shown, and the script fails.
rm -f "$tmp/secret"
if (STUB_HELM_FAIL=1 run); then helm_rc=0; else helm_rc=1; fi
check "helm failure fails the script" [ "$helm_rc" = 1 ]
check "token shown when helm fails" grep -q "bearer token (shown once" "$tmp/out"

# An existing backup directory keeps its mode.
mkdir -p "$tmp/mine" && chmod 750 "$tmp/mine"
(SCRAP_BACKUP_DIR=$tmp/mine run)
check "existing backup dir keeps its mode" sh -c "[ \"\$(stat -c %a '$tmp/mine')\" = 750 ]"
check "existing backup dir used" grep -q "hostPath: $tmp/mine" "$tmp/values.yaml"

# An existing backup directory you cannot write is refused.
mkdir -p "$tmp/ro" && chmod 500 "$tmp/ro"
if (SCRAP_BACKUP_DIR=$tmp/ro run); then ro_rc=0; else ro_rc=1; fi
check "unwritable backup dir refused" [ "$ro_rc" = 1 ]
check "unwritable backup dir explained" grep -q "cannot write to $tmp/ro" "$tmp/out"
chmod 700 "$tmp/ro"

# An existing Secret without the /mcp token stops before Helm.
touch "$tmp/secret" "$tmp/notoken"; : >"$tmp/helm.calls"
if run; then nt_rc=0; else nt_rc=1; fi
check "secret without token refused" [ "$nt_rc" = 1 ]
check "secret without token: no helm" sh -c "[ ! -s '$tmp/helm.calls' ]"
check "secret without token explained" grep -q "has no SCRAP_MCP_TOKEN" "$tmp/out"
rm -f "$tmp/notoken"

# Backups on a claim: no hostPath. A relative directory is refused.
(SCRAP_BACKUP_DIR='' run)
check "empty backup dir keeps the claim" sh -c "! grep -q hostPath '$tmp/values.yaml'"
if (SCRAP_BACKUP_DIR=rel run); then rel_rc=0; else rel_rc=1; fi
check "relative backup dir refused" [ "$rel_rc" = 1 ]

# No secret and no key: ingest off.
rm -f "$tmp/secret" "$tmp/key"
run
check "ingest off without a key" sh -c "grep -A1 '^ingest:' '$tmp/values.yaml' | grep -q 'enabled: false'"

exit $fail
