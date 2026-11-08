#!/bin/sh
# Tests for install-dls.sh with stub kubectl, helm and claude (no cluster needed), and
# HOME in a temp dir, so your own Claude Code and .env are never touched.
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
real_mktemp=$(command -v mktemp)
real_cat=$(command -v cat)
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
  *"get secret"*ANTHROPIC*) [ -e "$tmp/key" ] && echo eg== ; exit 0 ;;
  *"get secret"*SCRAP_MCP_TOKEN*)
    [ -e "$tmp/notoken" ] && exit 0
    [ -e "$tmp/oddtoken" ] && { base64 <"$tmp/oddtoken"; exit 0; }
    if [ -e "$tmp/created-SCRAP_MCP_TOKEN" ]; then base64 <"$tmp/created-SCRAP_MCP_TOKEN"; else echo dA==; fi
    exit 0 ;;
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
# claude: records calls; a user-scope server NAME is the file $tmp/claude-NAME. remove
# fails unless it is there; add-json fails on STUB_CLAUDE_FAIL.
cat >"$tmp/bin/claude" <<STUB
#!/bin/sh
echo "\$*" >>"$tmp/claude.calls"
case "\$*" in
  "mcp remove --scope user "*) rm "$tmp/claude-\$4" 2>/dev/null; exit \$? ;;
  "mcp add-json --scope user "*)
    [ -z "\${STUB_CLAUDE_FAIL:-}" ] || { echo "stub claude: no" >&2; exit 1; }
    printf '%s\\n' "\$5" >"$tmp/claude-\$4"; exit 0 ;;
esac
exit 1
STUB
# mktemp: with $tmp/fullenv, the new .env's copy goes where it cannot be written (as a
# full disk or quota would), so the write fails before the real .env is touched.
cat >"$tmp/bin/mktemp" <<STUB
#!/bin/sh
case "\$*" in
  */.env.*) [ -e "$tmp/fullenv" ] && { echo "$tmp/nowhere/.env.x"; exit 0; } ;;
esac
exec "$real_mktemp" "\$@"
STUB
# cat: with $tmp/cutenv, copying the new .env over the real one stops part way (as a
# full disk or quota would), after writing a few bytes.
cat >"$tmp/bin/cat" <<STUB
#!/bin/sh
case "\$*" in
  */.env.*) [ -e "$tmp/cutenv" ] && { head -c 5 "\$1"; exit 1; } ;;
esac
exec "$real_cat" "\$@"
STUB
chmod +x "$tmp/bin/"*
# The system's tools without any real claude, so a test can never reach yours: links to
# every command on the PATH (the first of each name, as the PATH would find it) but
# claude, in one directory, so no directory that also holds core tools is dropped.
mkdir "$tmp/sysbin"
printf %s "$PATH" | tr : '\n' | while read -r d; do
    [ -d "$d" ] || continue
    for f in "$d"/*; do
        n=${f##*/}
        if [ "$n" != claude ] && [ -f "$f" ] && [ -x "$f" ] && [ ! -e "$tmp/sysbin/$n" ]; then
            ln -s "$f" "$tmp/sysbin/$n"
        fi
    done
done
sys_path=$tmp/sysbin

# A key in the developer's shell must not reach the cases that run without one.
unset ANTHROPIC_API_KEY
# Detached from any terminal, so the key prompt cannot open /dev/tty and wait.
detached() {
    if setsid -w true 2>/dev/null; then setsid -w "$@"; else "$@"; fi
}
# A made-up fedid, so no name resolves on a DLS machine.
run() {
    mkdir -p "$tmp/installer-tmp"
    mkdir -p "$tmp/home"
    PATH="$tmp/bin:$sys_path" HOME="$tmp/home" USER=abc12345 SCRAP_BACKUP_DIR="${SCRAP_BACKUP_DIR-$tmp/science/scrap}" \
        TMPDIR="$tmp/installer-tmp" detached "$here/install-dls.sh" </dev/null >"$tmp/out" 2>&1
}

# Another scrap already set up for Claude Code: a server named scrap, its helper and its
# token in the .env. The installer must leave all three alone.
envf=$tmp/home/.config/terminal-config/.env
mkdir -p "$tmp/home/.claude" "${envf%/*}"
printf '#!/bin/sh\n# the home scrap\n' >"$tmp/home/.claude/scrap-headers.sh"
cp "$tmp/home/.claude/scrap-headers.sh" "$tmp/home-helper"
printf 'SCRAP_MCP_TOKEN=home\n' >"$envf"; chmod 600 "$envf"
echo home >"$tmp/claude-scrap"

# First run: key from the environment, token generated and shown once.
: >"$tmp/kubectl.calls"; : >"$tmp/claude.calls"; touch "$tmp/key"
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
check "ticket advice" grep -q "jira.diamond.ac.uk/servicedesk/customer/portal/2/create/91" "$tmp/out"
check "backup dir made, mode 700" sh -c "[ \"\$(stat -c %a '$tmp/science/scrap')\" = 700 ]"
check "backups on the host path" grep -q "hostPath: $tmp/science/scrap" "$tmp/values.yaml"
check "job cpu limits fit argus" [ "$(grep -c 'limits: {cpu: 500m' "$tmp/values.yaml")" = 4 ]
check "backup jobs have room to restore the database" grep -q "^  resources: {limits: {cpu: 500m, ephemeral-storage: 2Gi}}$" "$tmp/values.yaml"
check "the database moves off NFS" sh -c "grep -A1 '^litestream:' '$tmp/values.yaml' | grep -q 'enabled: true'"
check "says what can be lost" grep -q "last moments of writes are lost" "$tmp/out"
check "runs as the user" grep -q "runAsUser: $(id -u)" "$tmp/values.yaml"
check "containers name the user too (argus's Kyverno on upgrade)" sh -c "grep -A3 '^securityContext:' '$tmp/values.yaml' | tr -d '\n' |
    grep -q 'privileged: false *runAsUser: $(id -u) *runAsGroup: $(id -g)'"
check "no network policy" sh -c "! grep -q '^networkPolicy' '$tmp/values.yaml'"
# The login: the central proxy, letting in only the fedid the namespace is named for.
check "no namespace label read" sh -c "! grep -q 'get namespace' '$tmp/kubectl.calls'"
check "authProxy on" sh -c "grep -A1 '^authProxy:' '$tmp/values.yaml' | grep -q 'enabled: true'"
check "the central proxy's service" grep -q "^  service: oauth2-proxy.scrap.svc.cluster.local$" "$tmp/values.yaml"
check "only the owner's fedid" sh -c "grep -A1 '^  allowedUsers:' '$tmp/values.yaml' | grep -q '^    - \"abc12345\"$'"
check "says who it lets in" grep -q "let in only abc12345\.$" "$tmp/out"
check "no warning when the owner is you" sh -c "! grep -q 'not you' '$tmp/out'"
check "scrap checks DLS Keycloak's token" sh -c "grep -A2 '^  oidc:' '$tmp/values.yaml' | tr -d '\n' |
    grep -q 'issuer: \"https://identity.diamond.ac.uk/realms/dls\" *clientId: \"scrap-central-proxy\"'"
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
check "the Keycloak redirect, as a hint" grep -q "^     https://scrap-abc12345.diamond.ac.uk/oauth2/callback to the Keycloak client.$" "$tmp/out"
# Claude Code: the token in a private .env, the helper, and scrap-dls added for all projects.
helper=$tmp/home/.claude/scrap-dls-headers.sh
tok=$(cat "$tmp/created-SCRAP_MCP_TOKEN")
json='{"type":"http","url":"https://scrap-abc12345.diamond.ac.uk/mcp","headersHelper":"'$helper'"}'
# The helper exactly as the DLS explanation shows it (its indented block after "writes the helper").
awk '/writes the helper/ { f = 1; next }
     f && /^   ```sh$/ { b = 1; next }
     b && /^   ```$/ { exit }
     b { sub(/^   /, ""); print }' "$here/../docs/explanations/scrap-at-dls.md" >"$tmp/want-helper"
check "claude: the tutorial's helper found" grep -q '^#!/bin/sh$' "$tmp/want-helper"
check "claude: .env is mode 600" sh -c "[ \"\$(stat -c %a '$envf')\" = 600 ]"
check "claude: the token in .env" grep -qx "SCRAP_DLS_MCP_TOKEN=$tok" "$envf"
check "claude: helper is mode 700" sh -c "[ \"\$(stat -c %a '$helper')\" = 700 ]"
check "claude: helper as in the tutorial" cmp -s "$helper" "$tmp/want-helper"
check "claude: the helper reads the host's .env" sh -c "HOME='$tmp/home' '$helper' |
    grep -qxF '{\"Authorization\":\"Bearer $tok\"}'"
# In claude-sandbox the .env is at /user-terminal-config/.env: the same helper, with that
# path moved into $tmp, and a HOME with no .env.
mkdir -p "$tmp/sandbox-env" "$tmp/sandbox-home"
printf 'SCRAP_DLS_MCP_TOKEN=sandbox\n' >"$tmp/sandbox-env/.env"
sed "s|/user-terminal-config/.env|$tmp/sandbox-env/.env|" "$helper" >"$tmp/sandbox-helper"
check "claude: the helper reads claude-sandbox's .env" sh -c "HOME='$tmp/sandbox-home' sh '$tmp/sandbox-helper' |
    grep -qxF '{\"Authorization\":\"Bearer sandbox\"}'"
# A home .env without the token (as a container's might be): it goes on to the next.
mkdir -p "$tmp/sandbox-home/.config/terminal-config"
echo OTHER=1 >"$tmp/sandbox-home/.config/terminal-config/.env"
check "claude: the helper goes past an .env without the token" sh -c "HOME='$tmp/sandbox-home' sh '$tmp/sandbox-helper' |
    grep -qxF '{\"Authorization\":\"Bearer sandbox\"}'"
# An .env that is not valid shell: the helper reads only the token's line, runs nothing.
printf '%s\n' "A='unclosed" "\$(touch $tmp/ran-env)" SCRAP_DLS_MCP_TOKEN=old SCRAP_DLS_MCP_TOKEN=messy \
    >"$tmp/sandbox-env/.env"
check "claude: the helper reads only the token line of a messy .env" sh -c "HOME='$tmp/sandbox-home' sh '$tmp/sandbox-helper' |
    grep -qxF '{\"Authorization\":\"Bearer messy\"}' && [ ! -e '$tmp/ran-env' ]"
# Other ways a .env may hold it: after `export `, in "" or '', or with a CRLF ending.
for form in 'export SCRAP_DLS_MCP_TOKEN=tok' 'SCRAP_DLS_MCP_TOKEN="tok"' "SCRAP_DLS_MCP_TOKEN='tok'" \
    "$(printf 'SCRAP_DLS_MCP_TOKEN=tok\r')"; do
    printf 'OTHER=1\r\n%s\n' "$form" >"$tmp/sandbox-env/.env"
    check "claude: the helper reads $(printf %s "$form" | tr '\r' '^')" sh -c "HOME='$tmp/sandbox-home' sh '$tmp/sandbox-helper' |
        grep -qxF '{\"Authorization\":\"Bearer tok\"}'"
done
# No token anywhere: an error and exit 1, never an empty bearer.
: >"$tmp/sandbox-env/.env"
if HOME="$tmp/sandbox-home" sh "$tmp/sandbox-helper" >"$tmp/helper.out" 2>"$tmp/helper.err"; then hn_rc=0; else hn_rc=1; fi
check "claude: the helper fails with no token" [ "$hn_rc" = 1 ]
check "claude: the helper says why, and sends nothing" sh -c "[ ! -s '$tmp/helper.out' ] &&
    grep -q '^SCRAP_DLS_MCP_TOKEN not found in ~/.config/terminal-config/.env or ' '$tmp/helper.err'"
check "claude: scrap-dls added with the JSON" grep -qxF "mcp add-json --scope user scrap-dls $json" "$tmp/claude.calls"
check "claude: says it is connected" grep -q "Claude Code is connected to scrap for all your projects, as scrap-dls" "$tmp/out"
check "claude: no tutorial link when connected" sh -c "! grep -q 'install-dls-claude' '$tmp/out'"
check "mcp token never on a command line" sh -c "! grep -qF '$tok' '$tmp/kubectl.calls' '$tmp/helm.calls' '$tmp/claude.calls'"
cp "$tmp/values.yaml" "$tmp/first-values.yaml"

# SCRAP_VERSION picks the release.
: >"$tmp/helm.calls"
(SCRAP_VERSION=1.5.0 run)
check "SCRAP_VERSION passed to helm" grep -q -- "--version 1.5.0" "$tmp/helm.calls"
check "says which version" sh -c "head -n1 '$tmp/out' | grep -q 'Installing scrap 1.5.0 into'"

# Re-run: the secret exists, so no create and no token printed.
: >"$tmp/kubectl.calls"; : >"$tmp/claude.calls"
run
check "claude: the token once in .env after re-runs" [ "$(grep -c '^SCRAP_DLS_MCP_TOKEN=' "$envf")" = 1 ]
check "claude: re-run removes scrap-dls, then adds it" sh -c "[ \"\$(sed -n 1p '$tmp/claude.calls')\" = 'mcp remove --scope user scrap-dls' ] &&
    grep -qxF 'mcp add-json --scope user scrap-dls $json' '$tmp/claude.calls' && [ \"\$(wc -l <'$tmp/claude.calls')\" = 2 ]"
check "the other scrap: its server left alone" sh -c "[ \"\$(cat '$tmp/claude-scrap')\" = home ] &&
    ! grep -Eq ' scrap( |\$)' '$tmp/claude.calls'"
check "the other scrap: its helper left alone" cmp -s "$tmp/home/.claude/scrap-headers.sh" "$tmp/home-helper"
check "the other scrap: its token left alone" sh -c "[ \"\$(grep -c '^SCRAP_MCP_TOKEN=' '$envf')\" = 1 ] &&
    grep -qx SCRAP_MCP_TOKEN=home '$envf'"
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

# SCRAP_USER overrides the namespace; SCRAP_AUTH_NAMESPACE and _SERVICE move the proxy.
(SCRAP_USER=XYZ98765 SCRAP_AUTH_NAMESPACE=login run)
check "SCRAP_USER, lower case" grep -q '^    - "xyz98765"$' "$tmp/values.yaml"
check "warns when the owner is not you" grep -q "WARNING: scrap will let in only xyz98765, not you (abc12345): set SCRAP_USER" "$tmp/out"
check "SCRAP_AUTH_NAMESPACE" grep -q "^  service: oauth2-proxy.login.svc.cluster.local$" "$tmp/values.yaml"
(SCRAP_USER=ABC12345 run)
check "no warning for your fedid in upper case" sh -c "! grep -q 'not you' '$tmp/out'"
(SCRAP_OIDC_ISSUER=https://kc.example.org/realms/x SCRAP_OIDC_CLIENT_ID=mine run)
check "SCRAP_OIDC_ISSUER and _CLIENT_ID" sh -c "grep -A2 '^  oidc:' '$tmp/values.yaml' | tr -d '\n' |
    grep -q 'issuer: \"https://kc.example.org/realms/x\" *clientId: \"mine\"'"
(STUB_NS=ABC12345 SCRAP_AUTH_SERVICE=proxy.elsewhere.svc.cluster.local run)
check "the namespace's fedid, lower case" grep -q '^    - "abc12345"$' "$tmp/values.yaml"
check "SCRAP_AUTH_SERVICE" grep -q "^  service: proxy.elsewhere.svc.cluster.local$" "$tmp/values.yaml"

# A value that is not a fedid (an email, a space): stop before the Secret and Helm.
: >"$tmp/kubectl.calls"; : >"$tmp/helm.calls"; rm -f "$tmp/secret"
if (SCRAP_USER='giles.knap@diamond.ac.uk' run); then em_rc=0; else em_rc=1; fi
check "an email as SCRAP_USER refused" [ "$em_rc" = 1 ]
check "a bad fedid explained" grep -q "Set SCRAP_USER to your fedid" "$tmp/out"
check "a bad fedid: says the login is as it was" grep -q "if it had no login (SCRAP_LOGIN=off), it still has none" "$tmp/out"
check "a bad fedid: no Secret, no helm" sh -c "! grep -q 'create secret' '$tmp/kubectl.calls' && [ ! -s '$tmp/helm.calls' ]"
if (SCRAP_USER='a b' run); then sp_rc=0; else sp_rc=1; fi
check "a fedid with a space refused" [ "$sp_rc" = 1 ]
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
rm -f "$tmp/secret"; : >"$tmp/claude.calls"
if (STUB_HELM_FAIL=1 run); then helm_rc=0; else helm_rc=1; fi
check "helm failure fails the script" [ "$helm_rc" = 1 ]
check "token shown when helm fails" grep -q "bearer token (shown once" "$tmp/out"
check "helm failure: says the login is as it was" grep -q "if it had no login (SCRAP_LOGIN=off), it still has none" "$tmp/out"
check "helm failure: where to look if stuck in Init" grep -q "logs deploy/scrap -c db-init" "$tmp/out"
check "helm failure: claude left alone" sh -c "! grep -q 'add-json' '$tmp/claude.calls'"
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

# SCRAP_LOGIN=off: no login values, no fedid needed (a bad SCRAP_USER is ignored), the Secret and everything else kept,
# and a warning at both ends. Default and on: the login. Anything else: refused, untouched.
touch "$tmp/secret"
: >"$tmp/kubectl.calls"; : >"$tmp/helm.calls"
(SCRAP_LOGIN=off SCRAP_USER='not a fedid@x' run)
cp "$tmp/values.yaml" "$tmp/off-values.yaml"
check "login off: no authProxy, no oidc" sh -c "! grep -Eq 'authProxy|oidc|allowedUsers|issuer' '$tmp/values.yaml'"
check "login off: needs no fedid" sh -c "! grep -q 'Not a fedid' '$tmp/out' && ! grep -q 'let in only' '$tmp/out'"
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

# Claude Code: other lines in the .env kept, the token line replaced, the file made private.
printf 'OTHER=1\nSCRAP_DLS_MCP_TOKEN=old\nLAST=2' >"$envf"; chmod 644 "$envf"
run
check "claude: other .env lines kept" sh -c "grep -qx OTHER=1 '$envf' && grep -qx LAST=2 '$envf'"
check "claude: the old token line replaced" sh -c "[ \"\$(grep -c '^SCRAP_DLS_MCP_TOKEN=' '$envf')\" = 1 ] &&
    ! grep -q '^SCRAP_DLS_MCP_TOKEN=old' '$envf'"
check "claude: an open .env made private" sh -c "[ \"\$(stat -c %a '$envf')\" = 600 ]"

# No claude on the PATH: the install succeeds and says what to run.
mv "$tmp/bin/claude" "$tmp/claude.off"; : >"$tmp/claude.calls"
if run; then nc_rc=0; else nc_rc=1; fi
mv "$tmp/claude.off" "$tmp/bin/claude"
check "no claude: the install succeeds" [ "$nc_rc" = 0 ]
check "no claude: says so" grep -q "Claude Code was not found" "$tmp/out"
check "no claude: prints the command" grep -qxF "  claude mcp add-json --scope user scrap-dls '$json'" "$tmp/out"
check "no claude: links the DLS explanation" grep -q "scrap-at-dls.html#install-dls-claude" "$tmp/out"

# claude fails: warned, and the install still succeeds.
if (STUB_CLAUDE_FAIL=1 run); then cf_rc=0; else cf_rc=1; fi
check "claude fails: the install succeeds" [ "$cf_rc" = 0 ]
check "claude fails: warns" grep -q "WARNING: claude mcp add-json failed" "$tmp/out"
check "claude fails: says what to run" grep -q "fix the cause above, then run:" "$tmp/out"
check "claude fails: prints the command" grep -qxF "  claude mcp add-json --scope user scrap-dls '$json'" "$tmp/out"

# A fresh HOME, with no ~/.config at all: the directory and an empty .env are made,
# private even under a loose umask.
rm -rf "${tmp:?}/home"
if (umask 000 && run); then fh_rc=0; else fh_rc=1; fi
check "fresh home: the install succeeds" [ "$fh_rc" = 0 ]
check "fresh home: ~/.config and its terminal-config made mode 700" sh -c "
    [ \"\$(stat -c %a '$tmp/home/.config')\" = 700 ] && [ \"\$(stat -c %a '${envf%/*}')\" = 700 ]"
check "fresh home: .env holds only the token, mode 600" sh -c "[ \"\$(stat -c %a '$envf')\" = 600 ] &&
    [ \"\$(cat '$envf')\" = \"SCRAP_DLS_MCP_TOKEN=\$(cat '$tmp/created-SCRAP_MCP_TOKEN')\" ]"
check "fresh home: the helper made" cmp -s "$helper" "$tmp/want-helper"
check "fresh home: no copy of the .env left beside it" [ "$(ls -A "${envf%/*}")" = .env ]
check "fresh home: connected" grep -q "Claude Code is connected" "$tmp/out"

# The .env cannot be written (its directory is a file): warned, and the install succeeds.
rm -rf "${tmp:?}/home"; mkdir -p "$tmp/home/.config"; echo x >"$tmp/home/.config/terminal-config"
: >"$tmp/claude.calls"
if run; then nw_rc=0; else nw_rc=1; fi
check "no .env: the install succeeds" [ "$nw_rc" = 0 ]
check "no .env: warns" grep -q "WARNING: could not write the token to $envf" "$tmp/out"
check "no .env: says what to do" grep -q "fix the cause above, then re-run this script" "$tmp/out"
check "no .env: claude left alone" sh -c "[ ! -s '$tmp/claude.calls' ]"

# A token set by hand with characters the helper's shell would act on ($( ), or a
# leading ~ after the =): the meaningful check is that no SCRAP_DLS_MCP_TOKEN line
# reaches the .env the helper sources.
# shellcheck disable=SC2016,SC2088 # literal $( ) and ~ are the point
for odd in 'a$(touch '"$tmp"'/ran)b' '~/x'; do
    rm -rf "${tmp:?}/home"; printf '%s' "$odd" >"$tmp/oddtoken"; : >"$tmp/claude.calls"
    if run; then ot_rc=0; else ot_rc=1; fi
    rm -f "$tmp/oddtoken"
    check "odd token '$odd': the install succeeds" [ "$ot_rc" = 0 ]
    check "odd token '$odd': warns" grep -q "WARNING: the token in .* has characters other than" "$tmp/out"
    check "odd token '$odd': says what to do" grep -q "fix the cause above, then re-run this script" "$tmp/out"
    check "odd token '$odd': no token line in .env" sh -c "! grep -qs SCRAP_DLS_MCP_TOKEN '$envf'"
    check "odd token '$odd': claude left alone" sh -c "[ ! -s '$tmp/claude.calls' ] && [ ! -e '$tmp/ran' ]"
done

# Writing the new .env fails (a full disk or quota): the .env is left as it was.
rm -rf "${tmp:?}/home"; mkdir -p "${envf%/*}"
printf 'SCRAP_MCP_TOKEN=home\nSCRAP_DLS_MCP_TOKEN=old\n' >"$envf"; chmod 600 "$envf"
cp "$envf" "$tmp/want-env"; touch "$tmp/fullenv"; : >"$tmp/claude.calls"
if run; then fw_rc=0; else fw_rc=1; fi
rm -f "$tmp/fullenv"
check "write fails: the install succeeds" [ "$fw_rc" = 0 ]
check "write fails: warns" grep -q "WARNING: could not write the token to $envf" "$tmp/out"
check "write fails: the .env untouched" cmp -s "$envf" "$tmp/want-env"
check "write fails: claude left alone" sh -c "[ ! -s '$tmp/claude.calls' ]"

# The copy over the .env stops part way: the full new contents are kept in .env.bak.
rm -f "$envf.bak"; cp "$tmp/want-env" "$envf"; touch "$tmp/cutenv"; : >"$tmp/claude.calls"
if run; then cw_rc=0; else cw_rc=1; fi
rm -f "$tmp/cutenv"
check "cut short: the install succeeds" [ "$cw_rc" = 0 ]
check "cut short: says where the copy is" grep -qF "Its full new contents are in $envf.bak:" "$tmp/out"
check "cut short: says to restore it first" grep -qF "restore it first (mv '$envf.bak' '$envf'), then re-run this script." "$tmp/out"
check "cut short: .env.bak, mode 600, holds the other lines and the new token" sh -c "
    [ \"\$(stat -c %a '$envf.bak')\" = 600 ] && grep -qx 'SCRAP_MCP_TOKEN=home' '$envf.bak' &&
    [ \"\$(grep '^SCRAP_DLS_MCP_TOKEN=' '$envf.bak')\" = \"SCRAP_DLS_MCP_TOKEN=\$(cat '$tmp/created-SCRAP_MCP_TOKEN')\" ]"
check "cut short: no other copy left beside it" sh -c "[ \"\$(ls -A '${envf%/*}' | sort | tr '\n' ' ')\" = '.env .env.bak ' ]"
check "cut short: claude left alone" sh -c "[ ! -s '$tmp/claude.calls' ]"

# Cut short again, with that .env.bak still there: it is kept, and the new copy stays
# beside the .env under its temporary name, which the warning gives.
echo 'the older bak' >"$envf.bak"; cp "$tmp/want-env" "$envf"; touch "$tmp/cutenv"
if run; then cb_rc=0; else cb_rc=1; fi
rm -f "$tmp/cutenv"
check "cut short, .bak there: the install succeeds" [ "$cb_rc" = 0 ]
check "cut short, .bak there: the .bak kept" grep -qx 'the older bak' "$envf.bak"
cb_new=$(find "${envf%/*}" -name '.env.??????' | head -n 1)
check "cut short, .bak there: the new copy kept, mode 600, with the token" sh -c "[ -n '$cb_new' ] &&
    [ \"\$(stat -c %a '$cb_new')\" = 600 ] && grep -qx 'SCRAP_MCP_TOKEN=home' '$cb_new' &&
    grep -q '^SCRAP_DLS_MCP_TOKEN=' '$cb_new'"
check "cut short, .bak there: says to restore that copy" grep -qF "restore it first (mv '$cb_new' '$envf')" "$tmp/out"

# SCRAP_CLAUDE=off: no .env, no helper, no claude.
rm -rf "${tmp:?}/home"; : >"$tmp/claude.calls"
(SCRAP_CLAUDE=off run)
check "SCRAP_CLAUDE=off: nothing touched" sh -c "[ ! -e '$tmp/home/.config' ] && [ ! -e '$tmp/home/.claude' ] &&
    [ ! -s '$tmp/claude.calls' ]"
check "SCRAP_CLAUDE=off: says so" grep -q "Claude Code left alone (SCRAP_CLAUDE=off)" "$tmp/out"
for bad in OFF no 0 'on '; do
    : >"$tmp/kubectl.calls"; : >"$tmp/helm.calls"; : >"$tmp/claude.calls"; rm -rf "${tmp:?}/home"
    if (SCRAP_CLAUDE=$bad run); then bad_rc=0; else bad_rc=1; fi
    check "SCRAP_CLAUDE='$bad' refused" [ "$bad_rc" = 1 ]
    check "SCRAP_CLAUDE='$bad': nothing touched" sh -c "[ ! -s '$tmp/helm.calls' ] && [ ! -s '$tmp/kubectl.calls' ] &&
        [ ! -s '$tmp/claude.calls' ] && [ -z \"\$(ls -A '$tmp/home')\" ]"
    check "SCRAP_CLAUDE='$bad' explained" grep -q "SCRAP_CLAUDE must be on or off" "$tmp/out"
done

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
        ! grep -Eq 'auth-url|auth-signin|SCRAP_OIDC|SCRAP_ALLOWED_USERS|ExternalName|name: scrap-open' "$tmp/off.yaml" &&
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
