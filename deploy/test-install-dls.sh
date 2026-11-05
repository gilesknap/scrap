#!/bin/sh
# Tests for install-dls.sh with stub kubectl/helm (no cluster needed).
# Run: ./deploy/test-install-dls.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
fail=0
# The real helm and kubeconform, if any, before the stubs go on the PATH.
real_helm=$(command -v helm || true)
real_kubeconform=$(command -v kubeconform || true)
check() { # check NAME CONDITION-COMMAND...
    name=$1; shift
    if "$@"; then echo "ok   $name"; else echo "FAIL $name"; fail=1; fi
}

# kubectl: records calls; `get secret` succeeds only once $tmp/secret exists. It keeps
# copies of the files a Secret is made or patched from, in $tmp/created-<key> and
# $tmp/patch.json.
cat >"$tmp/bin/kubectl" <<STUB
#!/bin/sh
echo "\$*" >>"$tmp/kubectl.calls"
case "\$*" in
  *"create secret"*)
    touch "$tmp/secret"
    for a in "\$@"; do
      case "\$a" in --from-file=*) kv=\${a#--from-file=}; cp "\${kv#*=}" "$tmp/created-\${kv%%=*}" ;; esac
    done
    exit 0 ;;
  *"patch secret"*)
    while [ \$# -gt 0 ]; do [ "\$1" = --patch-file ] && cp "\$2" "$tmp/patch.json"; shift; done
    exit 0 ;;
  *"get namespace"*) printf '%s' "\${STUB_EMAIL_LABEL-giles.knap--at--diamond.ac.uk}"; exit 0 ;;
  *"get secret"*ANTHROPIC*) [ -e "$tmp/key" ] && echo eg== ; exit 0 ;;
  *"get secret"*SCRAP_MCP_TOKEN*) [ -e "$tmp/notoken" ] || echo dA== ; exit 0 ;;
  *"get secret"*SCRAP_PUBLISH_TOKEN*) [ -e "$tmp/nopublish" ] || echo cA== ; exit 0 ;;
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
# A made-up fedid, so no name resolves on a DLS machine.
run() {
    mkdir -p "$tmp/installer-tmp"
    PATH="$tmp/bin:$PATH" USER=abc12345 SCRAP_BACKUP_DIR="${SCRAP_BACKUP_DIR-$tmp/science/scrap}" \
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
check "namespace falls back to USER" grep -q -- "--namespace abc12345" "$tmp/helm.calls"
check "host from USER" grep -q "scrap-abc12345.diamond.ac.uk" "$tmp/values.yaml"
check "nginx class by default" grep -q "className: nginx" "$tmp/values.yaml"
check "tls for the host" grep -A2 -q "tls:" "$tmp/values.yaml"
check "ingest enabled" sh -c "grep -A1 '^ingest:' '$tmp/values.yaml' | grep -q 'enabled: true'"
check "token shown" grep -q "bearer token (shown once" "$tmp/out"
check "service ip shown" grep -q "10.1.2.3" "$tmp/out"
check "clusterip by default" grep -q "type: ClusterIP" "$tmp/values.yaml"
check "ticket advice" grep -q "jira.diamond.ac.uk/servicedesk/customer/portal/2/create/156" "$tmp/out"
check "backup dir made, mode 700" sh -c "[ \"\$(stat -c %a '$tmp/science/scrap')\" = 700 ]"
check "backups on the host path" grep -q "hostPath: $tmp/science/scrap" "$tmp/values.yaml"
check "job cpu limits fit argus" [ "$(grep -c 'limits: {cpu: 500m' "$tmp/values.yaml")" = 4 ]
check "backup jobs have room to restore the database" grep -q "^  resources: {limits: {cpu: 500m, ephemeral-storage: 2Gi}}$" "$tmp/values.yaml"
check "the database moves off NFS" sh -c "grep -A1 '^litestream:' '$tmp/values.yaml' | grep -q 'enabled: true'"
check "says what can be lost" grep -q "last moments of writes are lost" "$tmp/out"
check "runs as the user" grep -q "runAsUser: $(id -u)" "$tmp/values.yaml"
check "no network policy" sh -c "! grep -q '^networkPolicy' '$tmp/values.yaml'"
# The login: the central proxy, letting in only the email from the namespace's label.
check "email from the namespace label" grep -q -- "get namespace abc12345" "$tmp/kubectl.calls"
check "authProxy on" sh -c "grep -A1 '^authProxy:' '$tmp/values.yaml' | grep -q 'enabled: true'"
check "the central proxy's service" grep -q "^  service: oauth2-proxy.scrap.svc.cluster.local$" "$tmp/values.yaml"
check "only the owner's email" sh -c "grep -A1 '^  allowedEmails:' '$tmp/values.yaml' | grep -q '^    - \"giles.knap@diamond.ac.uk\"$'"
check "scrap checks DLS Keycloak's token" sh -c "grep -A2 '^  oidc:' '$tmp/values.yaml' | tr -d '\n' |
    grep -q 'issuer: \"https://identity.diamond.ac.uk/realms/dls\" *clientId: \"scrap\"'"
check "says a direct call gets 401" grep -q "directly without your login gets 401" "$tmp/out"
# Public pages: on, in this namespace, on pages-<fedid>, with a key of the one Secret.
check "body size: maxUploadMB plus a margin" sh -c "grep -qx 'maxUploadMB: 50' '$tmp/values.yaml' &&
    grep -A2 '^ingress:' '$tmp/values.yaml' | grep -q '^  enabled: true' &&
    sed -n '/^ingress:/,/^[a-z]/p' '$tmp/values.yaml' |
    grep -qx '    nginx.ingress.kubernetes.io/proxy-body-size: \"51m\"'"
check "public on" sh -c "grep -A1 '^public:' '$tmp/values.yaml' | grep -q 'enabled: true'"
check "public in the namespace" grep -q "^  namespace: abc12345$" "$tmp/values.yaml"
check "public site" grep -q "^  site: https://pages-abc12345.diamond.ac.uk$" "$tmp/values.yaml"
check "public token in scrap-secrets" sh -c "grep -A2 '^  tokenSecret:' '$tmp/values.yaml' | tr -d '\n' |
    grep -q 'name: scrap-secrets *key: SCRAP_PUBLISH_TOKEN'"
check "public ingress host and tls" [ "$(grep -c -- '- pages-abc12345.diamond.ac.uk$' "$tmp/values.yaml")" = 2 ]
check "public network policy off" sh -c "grep -A1 '^  networkPolicy:' '$tmp/values.yaml' | grep -q 'enabled: false'"
check "public cpu limits fit argus" [ "$(grep -c 'limits: {cpu: 100m}' "$tmp/values.yaml")" = 2 ]
check "publish token made with the Secret" sh -c "grep -Eqx '[0-9a-f]{64}' '$tmp/created-SCRAP_PUBLISH_TOKEN'"
check "publish token never on a command line" sh -c "! grep -qF \"\$(cat '$tmp/created-SCRAP_PUBLISH_TOKEN')\" '$tmp/kubectl.calls' '$tmp/helm.calls'"
check "no patch for a new Secret" sh -c "! grep -q 'patch secret' '$tmp/kubectl.calls'"
check "asks for both names" sh -c "grep -q '^         scrap-abc12345.diamond.ac.uk$' '$tmp/out' &&
    grep -q '^         pages-abc12345.diamond.ac.uk$' '$tmp/out'"
check "asks for the Keycloak redirect" grep -q "^         https://scrap-abc12345.diamond.ac.uk/oauth2/callback$" "$tmp/out"
cp "$tmp/values.yaml" "$tmp/first-values.yaml"

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
check "no patch when the publish key exists" sh -c "! grep -q 'patch secret' '$tmp/kubectl.calls'"

# An existing Secret without the publish key: only that key is added, from a file.
: >"$tmp/kubectl.calls"; touch "$tmp/nopublish"
run
check "publish key added" grep -q "patch secret scrap-secrets --type merge --patch-file" "$tmp/kubectl.calls"
check "patch holds only the publish key" sh -c "sed 's/\"SCRAP_PUBLISH_TOKEN\":\"[A-Za-z0-9+\/=]*\"/K/' '$tmp/patch.json' |
    grep -qx '{\"data\":{K}}'"
pub=$(sed 's/.*"SCRAP_PUBLISH_TOKEN":"\([^"]*\)".*/\1/' "$tmp/patch.json" | base64 -d)
check "patched token: 64 hex characters" sh -c "printf %s '$pub' | grep -Eqx '[0-9a-f]{64}'"
check "patched token never on a command line" sh -c "! grep -qF '$pub' '$tmp/kubectl.calls' '$tmp/helm.calls'"
check "patch's temp files removed" sh -c "[ -z \"\$(ls -A '$tmp/installer-tmp')\" ]"
rm -f "$tmp/nopublish"

# SCRAP_EMAIL overrides the label; SCRAP_AUTH_NAMESPACE and _SERVICE move the proxy.
(SCRAP_EMAIL=Someone.Else@Diamond.ac.uk SCRAP_AUTH_NAMESPACE=login run)
check "SCRAP_EMAIL, lower case" grep -q '^    - "someone.else@diamond.ac.uk"$' "$tmp/values.yaml"
check "SCRAP_AUTH_NAMESPACE" grep -q "^  service: oauth2-proxy.login.svc.cluster.local$" "$tmp/values.yaml"
(SCRAP_OIDC_ISSUER=https://kc.example.org/realms/x SCRAP_OIDC_CLIENT_ID=mine run)
check "SCRAP_OIDC_ISSUER and _CLIENT_ID" sh -c "grep -A2 '^  oidc:' '$tmp/values.yaml' | tr -d '\n' |
    grep -q 'issuer: \"https://kc.example.org/realms/x\" *clientId: \"mine\"'"
(STUB_EMAIL_LABEL=Giles.Knap--at--Diamond.ac.uk SCRAP_AUTH_SERVICE=proxy.elsewhere.svc.cluster.local run)
check "label email, lower case" grep -q '^    - "giles.knap@diamond.ac.uk"$' "$tmp/values.yaml"
check "SCRAP_AUTH_SERVICE" grep -q "^  service: proxy.elsewhere.svc.cluster.local$" "$tmp/values.yaml"

# No email anywhere, or a value that is not one: stop before the Secret and Helm.
: >"$tmp/kubectl.calls"; : >"$tmp/helm.calls"; rm -f "$tmp/secret"
if (STUB_EMAIL_LABEL='' run); then ne_rc=0; else ne_rc=1; fi
check "no email refused" [ "$ne_rc" = 1 ]
check "no email explained" grep -q "Set SCRAP_EMAIL" "$tmp/out"
check "no email: says the login is as it was" grep -q "if it had no login (SCRAP_LOGIN=off), it still has none" "$tmp/out"
check "no email: no Secret, no helm" sh -c "! grep -q 'create secret' '$tmp/kubectl.calls' && [ ! -s '$tmp/helm.calls' ]"
if (SCRAP_EMAIL='a b@diamond.ac.uk' run); then be_rc=0; else be_rc=1; fi
check "a bad email refused" [ "$be_rc" = 1 ]
if (SCRAP_EMAIL='fedid' run); then fe_rc=0; else fe_rc=1; fi
check "an email without @ refused" [ "$fe_rc" = 1 ]
touch "$tmp/secret"

(SCRAP_SERVICE_TYPE=LoadBalancer run)
check "loadbalancer opt-in" grep -q "type: LoadBalancer" "$tmp/values.yaml"
check "external ip shown" grep -q "192.0.2.7" "$tmp/out"

# Options: ingress class, namespace from kubectl context; always https.
(STUB_NS=work SCRAP_INGRESS_CLASS=internal run)
check "namespace from context" grep -q -- "--namespace work" "$tmp/helm.calls"
check "https in the first line" sh -c "head -n1 '$tmp/out' | grep -q 'for https://scrap-'"
check "ingress class" [ "$(grep -c "className: internal" "$tmp/values.yaml")" = 2 ]

# Names that already resolve need no ticket.
(SCRAP_HOST=localhost SCRAP_PAGES_HOST=localhost run)
check "no ticket when the names resolve" sh -c "! grep -q 'servicedesk' '$tmp/out'"
(SCRAP_HOST=localhost run)
check "ticket for the missing name only" sh -c "grep -q '^         pages-abc12345.diamond.ac.uk$' '$tmp/out' &&
    ! grep -q '^         localhost$' '$tmp/out'"

# Helm fails on the first run: the new token is still shown, and the script fails.
rm -f "$tmp/secret"
if (STUB_HELM_FAIL=1 run); then helm_rc=0; else helm_rc=1; fi
check "helm failure fails the script" [ "$helm_rc" = 1 ]
check "token shown when helm fails" grep -q "bearer token (shown once" "$tmp/out"
check "helm failure: says the login is as it was" grep -q "if it had no login (SCRAP_LOGIN=off), it still has none" "$tmp/out"
check "helm failure: where to look if stuck in Init" grep -q "logs deploy/scrap -c db-init" "$tmp/out"
check "helm failure: an older chart explained" grep -q "additional properties 'litestream' not allowed" "$tmp/out"

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

# SCRAP_LOGIN=off: no login values, no email needed, the Secret and everything else kept,
# and a warning at both ends. Default and on: the login. Anything else: refused, untouched.
touch "$tmp/secret"
: >"$tmp/kubectl.calls"; : >"$tmp/helm.calls"
(SCRAP_LOGIN=off STUB_EMAIL_LABEL='' run)
cp "$tmp/values.yaml" "$tmp/off-values.yaml"
check "login off: no authProxy, no oidc" sh -c "! grep -Eq 'authProxy|oidc|allowedEmails|issuer' '$tmp/values.yaml'"
check "login off: needs no email" sh -c "! grep -q 'get namespace' '$tmp/kubectl.calls'"
check "login off: warns twice" [ "$(grep -c '^WARNING: SCRAP_LOGIN=off' "$tmp/out")" = 2 ]
check "login off: warned before Helm ran" sh -c "sed -n 1,6p '$tmp/out' | grep -q 'NO LOGIN'"
check "login off: says who can read" sh -c "grep -q 'Anyone on the DLS network can read' '$tmp/out' &&
    grep -q 'any pod in the cluster' '$tmp/out' && grep -q 'Test data only' '$tmp/out' &&
    grep -q 're-run this script without SCRAP_LOGIN=off' '$tmp/out'"
check "login off: no Keycloak next step" sh -c "! grep -q 'oauth2/callback' '$tmp/out' && ! grep -q 'Keycloak' '$tmp/out'"
check "login off: keeps the secret" sh -c "! grep -q 'create secret' '$tmp/kubectl.calls'"
check "login off: /mcp keeps its token" sh -c "grep -A2 '^mcp:' '$tmp/values.yaml' | grep -q 'name: scrap-secrets'"
check "login off: backups, pages and the database as normal" sh -c "grep -q 'hostPath: ' '$tmp/values.yaml' &&
    grep -A1 '^public:' '$tmp/values.yaml' | grep -q 'enabled: true' &&
    grep -A1 '^litestream:' '$tmp/values.yaml' | grep -q 'enabled: true'"
# Re-run without it, from that install: the login is back, and the Secret kept.
: >"$tmp/kubectl.calls"
run
check "login back on: authProxy" sh -c "grep -A1 '^authProxy:' '$tmp/values.yaml' | grep -q 'enabled: true'"
check "login back on: no warning" sh -c "! grep -q 'SCRAP_LOGIN=off' '$tmp/out'"
check "login back on: keeps the secret" sh -c "! grep -q 'create secret' '$tmp/kubectl.calls'"
check "login back on: the Keycloak step" grep -q "oauth2/callback" "$tmp/out"
cp "$tmp/values.yaml" "$tmp/on-values.yaml"
(SCRAP_LOGIN=on run)
check "SCRAP_LOGIN=on is the default" cmp -s "$tmp/values.yaml" "$tmp/on-values.yaml"
for bad in OFF Off false 0 no 'off ' disabled; do
    : >"$tmp/kubectl.calls"; : >"$tmp/helm.calls"
    if (SCRAP_LOGIN=$bad run); then bad_rc=0; else bad_rc=1; fi
    check "SCRAP_LOGIN='$bad' refused" [ "$bad_rc" = 1 ]
    check "SCRAP_LOGIN='$bad': nothing touched" sh -c "[ ! -s '$tmp/helm.calls' ] && [ ! -s '$tmp/kubectl.calls' ]"
    check "SCRAP_LOGIN='$bad' explained" grep -q "SCRAP_LOGIN must be on or off" "$tmp/out"
done

# Backups on a claim: no hostPath. A relative directory is refused.
(SCRAP_BACKUP_DIR='' run)
check "empty backup dir keeps the claim" sh -c "! grep -q hostPath '$tmp/values.yaml'"
if (SCRAP_BACKUP_DIR=rel run); then rel_rc=0; else rel_rc=1; fi
check "relative backup dir refused" [ "$rel_rc" = 1 ]

# No secret and no key: ingest off.
rm -f "$tmp/secret" "$tmp/key"
run
check "ingest off without a key" sh -c "grep -A1 '^ingest:' '$tmp/values.yaml' | grep -q 'enabled: false'"

# The values the installer writes, through the real chart, when helm and kubeconform
# are on the PATH (CI's deploy job has neither: skipped there).
if [ -n "$real_helm" ] && [ -n "$real_kubeconform" ]; then
    if KUBECONFIG=/dev/null "$real_helm" template scrap "$here/../charts/scrap" --namespace abc12345 \
        -f "$tmp/first-values.yaml" >"$tmp/rendered.yaml" &&
        "$real_kubeconform" -strict -summary "$tmp/rendered.yaml" >/dev/null &&
        [ "$(grep -c '^kind: Ingress$' "$tmp/rendered.yaml")" = 3 ] &&
        ! grep -q '^kind: NetworkPolicy$' "$tmp/rendered.yaml"; then
        echo "ok   the installer's values render: three Ingresses, no NetworkPolicy"
    else
        echo "FAIL the installer's values do not render"
        fail=1
    fi
    # Login off, and back on: the same Ingress objects' change, through the chart.
    if KUBECONFIG=/dev/null "$real_helm" template scrap "$here/../charts/scrap" --namespace abc12345 \
        -f "$tmp/off-values.yaml" >"$tmp/off.yaml" &&
        KUBECONFIG=/dev/null "$real_helm" template scrap "$here/../charts/scrap" --namespace abc12345 \
        -f "$tmp/on-values.yaml" >"$tmp/on.yaml" &&
        "$real_kubeconform" -strict -summary "$tmp/off.yaml" >/dev/null &&
        "$real_kubeconform" -strict -summary "$tmp/on.yaml" >/dev/null &&
        [ "$(grep -c '^kind: Ingress$' "$tmp/off.yaml")" = 2 ] &&
        ! grep -Eq 'auth-url|auth-signin|SCRAP_OIDC|SCRAP_ALLOWED_EMAILS|ExternalName|name: scrap-open' "$tmp/off.yaml" &&
        grep -q 'name: SCRAP_MCP_TOKEN$' "$tmp/off.yaml" &&
        [ "$(grep -c '^kind: Ingress$' "$tmp/on.yaml")" = 3 ] &&
        grep -q 'auth-url' "$tmp/on.yaml" && grep -q 'name: SCRAP_OIDC_ISSUER' "$tmp/on.yaml" &&
        grep -q 'name: scrap-open' "$tmp/on.yaml" && grep -q 'ExternalName' "$tmp/on.yaml" &&
        ! grep -q '^kind: Secret$' "$tmp/off.yaml" && ! grep -q '^kind: Secret$' "$tmp/on.yaml"; then
        echo "ok   login off renders a plain Ingress, and back on the auth, the open Ingress and OIDC"
    else
        echo "FAIL login off or back on does not render as it should"
        fail=1
    fi
else
    echo "skip the installer's values through the chart (no helm or kubeconform)"
fi

exit $fail
