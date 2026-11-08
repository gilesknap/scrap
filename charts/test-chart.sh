#!/bin/sh
# Checks for the Helm chart: helm lint, helm template over the values in
# charts/scrap/ci/, kubeconform against the Kubernetes schemas, and that no
# template renders a secret. Needs helm and kubeconform on PATH.
#   ./charts/test-chart.sh
set -eu

chart=$(cd "$(dirname "$0")/scrap" && pwd)
k8s_versions=${K8S_VERSIONS:-"1.30.0 1.36.5"}
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
fail=0
ok() { echo "ok   $1"; }
bad() {
    echo "FAIL $1"
    fail=1
}

for values in "$chart"/ci/*-values.yaml; do
    name=$(basename "$values" -values.yaml)
    release=scrap
    # public's and authProxy's names gain suffixes, so they are rendered with the
    # longest name too
    if [ "$name" = long-names ] || [ "$name" = public ] || [ "$name" = auth-proxy ]; then
        release=a-release-name-of-fifty-three-characters-the-maximum
    fi
    if ! helm lint --strict --quiet "$chart" -f "$values" >"$out/lint" 2>&1; then
        cat "$out/lint"
        bad "$name: helm lint"
        continue
    fi
    if ! helm template "$release" "$chart" -f "$values" >"$out/$name.yaml" 2>"$out/err"; then
        cat "$out/err"
        bad "$name: helm template"
        continue
    fi
    m="$out/$name.yaml"
    for v in $k8s_versions; do
        if kubeconform -strict -summary -kubernetes-version "$v" "$m"; then
            ok "$name: kubeconform $v"
        else
            bad "$name: kubeconform $v"
        fi
    done
    # The chart never creates Secrets or ConfigMaps, and the key only ever
    # comes from a secretKeyRef.
    if grep -Eq '^kind: (Secret|ConfigMap)$' "$m"; then bad "$name: renders a Secret/ConfigMap"; fi
    if grep -A1 -E 'name: (ANTHROPIC_API_KEY|SCRAP_NOTIFY_URL|SCRAP_MCP_TOKEN|SCRAP_PUBLISH_TOKEN|RECEIVER_TOKEN)$' "$m" | grep -Eq 'value:'; then
        bad "$name: a secret setting rendered as a plain value"
    fi
    if [ "$(grep -c '^  replicas: 1$' "$m")" != "$(grep -c '^kind: Deployment$' "$m")" ] ||
        [ "$(grep -c 'type: Recreate' "$m")" != "$(grep -c '^kind: Deployment$' "$m")" ]; then
        bad "$name: not one replica with Recreate"
    fi
    # Kubernetes name limits: a CronJob's name 52, other names and label values 63
    # (PVC names may be longer).
    long=$(awk '/^kind: /{kind=$2} /^  name: /{n=$2; if ((kind=="CronJob" && length(n)>52) || (kind!="PersistentVolumeClaim" && length(n)>63)) print kind, n}
        /^ +(app\.kubernetes\.io|helm\.sh)\/[a-z-]+: /{v=$2; gsub(/"/,"",v); if (length(v)>63) print "label", v}' "$m")
    if [ -n "$long" ]; then bad "$name: too long: $(echo "$long" | tr "\n" " ")"; fi
    if [ "$(grep -c '^  revisionHistoryLimit: 2$' "$m")" != "$(grep -c '^kind: Deployment$' "$m")" ]; then
        bad "$name: a Deployment without revisionHistoryLimit: 2"
    fi
    if [ "$(grep -c '^      ttlSecondsAfterFinished: 604800$' "$m")" != "$(grep -c '^kind: CronJob$' "$m")" ]; then
        bad "$name: a CronJob without ttlSecondsAfterFinished: 604800"
    fi
    ok "$name: rendered, no secrets, one replica, history limits, names fit"
done

# Values that must be refused.
expect_refused() { # DESCRIPTION helm-args...
    d=$1
    shift
    if helm template scrap "$chart" "$@" >/dev/null 2>&1; then bad "refuses $d"; else ok "refuses $d"; fi
}
expect_refused "ingest without existingSecret" --set ingest.enabled=true
expect_refused "an API key as a value" --set ingest.apiKey=not-a-key
expect_refused "an unknown top-level key" --set replicas=2
expect_refused "backup.keep=0" --set backup.keep=0
expect_refused "backup.keep=-1" --set backup.keep=-1
expect_refused "backup.monthly.keep=0" --set backup.monthly.keep=0
expect_refused "a relative backup hostPath" --set backup.persistence.hostPath=backups
expect_refused "a non-numeric budget" --set ingest.budgetDayUSD=lots
expect_refused "an MCP token as a value" --set mcp.token=not-a-token
expect_refused "an MCP token as a tokenSecret value" --set mcp.tokenSecret.value=not-a-token
expect_refused "an empty tokenSecret key" --set mcp.tokenSecret.name=s --set mcp.tokenSecret.key=
expect_refused "an identityHeader that is not a header name" --set 'identityHeader=a b'
expect_refused "a negative budget" --set ingest.budgetDayUSD=-1
expect_refused "gc.enabled=true with backups off" --set backup.enabled=false --set gc.enabled=true
expect_refused "gc.trashDays=0" --set gc.trashDays=0
expect_refused "gc.jobDays=0.5" --set gc.jobDays=0.5
expect_refused "gc.trashDays over 36500" --set gc.trashDays=36501
expect_refused "public.enabled without tokenSecret.name" --set public.enabled=true \
    --set public.site=https://pages.example.org
expect_refused "public.enabled without site" --set public.enabled=true \
    --set public.tokenSecret.name=s
expect_refused "a public token as a value" --set public.token=not-a-token
expect_refused "a public site that is not a URL" --set public.site=pages.example.org
expect_refused "an unknown public key" --set public.replicas=2
expect_refused "public.createNamespace in the release namespace" --namespace scrap \
    -f "$chart/ci/public-same-namespace-values.yaml" --set public.createNamespace=true
expect_refused "authProxy without ingress" -f "$chart/ci/auth-proxy-values.yaml" \
    --set ingress.enabled=false
expect_refused "authProxy without service" -f "$chart/ci/auth-proxy-values.yaml" \
    --set authProxy.service=
expect_refused "authProxy without allowedUsers" -f "$chart/ci/auth-proxy-values.yaml" \
    --set 'authProxy.allowedUsers=null'
expect_refused "authProxy with an empty allowedUsers" -f "$chart/ci/auth-proxy-values.yaml" \
    --set 'authProxy.allowedUsers={}'
expect_refused "authProxy without an /mcp token" -f "$chart/ci/auth-proxy-values.yaml" \
    --set mcp.tokenSecret.name=
expect_refused "authProxy without tls" -f "$chart/ci/auth-proxy-values.yaml" \
    --set 'ingress.tls=null'
expect_refused "authProxy with a username with a space" -f "$chart/ci/auth-proxy-values.yaml" \
    --set 'authProxy.allowedUsers[0]=a b'
expect_refused "authProxy with the old allowedEmails" -f "$chart/ci/auth-proxy-values.yaml" \
    --set 'authProxy.allowedEmails[0]=first.last@example.org'
expect_refused "authProxy with a service that is not a DNS name" -f "$chart/ci/auth-proxy-values.yaml" \
    --set 'authProxy.service=http://proxy'
expect_refused "authProxy without oidc.issuer" -f "$chart/ci/auth-proxy-values.yaml" \
    --set authProxy.oidc.issuer=
expect_refused "authProxy without oidc.clientId" -f "$chart/ci/auth-proxy-values.yaml" \
    --set authProxy.oidc.clientId=
expect_refused "authProxy with an http oidc.issuer" -f "$chart/ci/auth-proxy-values.yaml" \
    --set authProxy.oidc.issuer=http://identity.example.org/realms/dls
expect_refused "an unknown litestream key" --set litestream.replicas=2
expect_refused "a litestream sizeLimit that is not one" --set litestream.sizeLimit=lots
expect_refused "@every with Litestream" --set litestream.enabled=true --set-string 'gc.schedule=@every 1h'
expect_refused "a four-field schedule with Litestream" --set litestream.enabled=true --set-string 'gc.schedule=1 2 3 4'
expect_refused "a litestream digest that is not one" --set litestream.image.digest=latest
expect_refused "the jobs' metrics on scrap's port" --set litestream.jobs.metrics.port=8000
expect_refused "an unknown jobs metrics key" --set litestream.jobs.metrics.path=/m
# Below 1.29 (native sidecars) Chart.yaml's kubeVersion refuses, in either mode, before any
# template runs: so _litestream.tpl's own 1.29 check is never reached now.
for mode in true false; do
    if helm template scrap "$chart" --set litestream.enabled=$mode --kube-version 1.28.0 2>&1 >/dev/null |
        grep -q 'requires kubeVersion: >=1.29'; then
        ok "refuses Kubernetes 1.28 with litestream.enabled=$mode, on kubeVersion"
    else bad "Kubernetes 1.28 with litestream.enabled=$mode is not refused on kubeVersion"; fi
done
expect_refused "litestream with gc but no backups" --set litestream.enabled=true \
    --set backup.enabled=false --set gc.enabled=true
expect_refused "an unknown authProxy.oidc key" -f "$chart/ci/auth-proxy-values.yaml" \
    --set authProxy.oidc.clientSecret=x

# Public pages (issue 497). Off by default: nothing of it renders, and scrap gets no
# SCRAP_PUBLISH_* settings.
if helm template scrap "$chart" | grep -Eq 'scrap-public|SCRAP_PUBLISH_'; then
    bad "public pages render while public.enabled is off"
else ok "public pages are off by default"; fi
pub="$out/public-checks.yaml"
helm template scrap "$chart" -f "$chart/ci/public-values.yaml" >"$pub"
# Each object as one line: kind, namespace, name, then its text joined with |
awk 'function end_doc() { if (doc != "") print doc; doc = "" }
    /^---/ { end_doc(); next } { doc = doc $0 "|" } END { end_doc() }' "$pub" >"$out/docs"
ingresses=$(grep '|kind: Ingress|' "$out/docs" || true)
if echo "$ingresses" | grep -Eq 'scrap-receiver|name: receiver|8081'; then
    bad "an Ingress points at the receiver"
elif echo "$ingresses" | grep 'namespace: scrap-public|' | grep -q '|                name: scrap-public|'; then
    ok "the only public Ingress is nginx's"
else bad "no Ingress for nginx"; fi
# The public NetworkPolicy, exactly: the receiver's port (8081) only from scrap's
# own pods in the release namespace, nginx's (8080) from webFrom (anyone when it
# is empty), and no egress at all.
np_spec() { # helm-args... -> the NetworkPolicy's spec
    helm template scrap "$chart" --namespace scrap -s templates/public.yaml "$@" |
        awk '/^---/ { np = 0 } /^kind: NetworkPolicy$/ { np = 1 } np && /^spec:$/ { on = 1 }
            np && on { print }'
}
np_head='spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: scrap-public
      app.kubernetes.io/instance: scrap
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: scrap
          podSelector:
            matchLabels:
              app.kubernetes.io/name: scrap
              app.kubernetes.io/instance: scrap
      ports:
        - port: receiver
    - ports:
        - port: web'
np_from='      from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx'
if [ "$(np_spec -f "$chart/ci/public-values.yaml")" = "$np_head
$np_from
  egress: []" ] && [ "$(np_spec -f "$chart/ci/public-namespace-values.yaml")" = "$np_head
  egress: []" ]; then
    ok "the public NetworkPolicy: 8081 from scrap's pods only, 8080 from webFrom, no egress"
else bad "the public NetworkPolicy is not exactly as it should be"; fi
# ... and the named ports are those numbers
pubdep=$(grep '|kind: Deployment|' "$out/docs" | grep 'namespace: scrap-public|' || true)
if echo "$pubdep" | grep -q '|            - name: web|              containerPort: 8080|' &&
    echo "$pubdep" | grep -q '|            - name: receiver|              containerPort: 8081|'; then
    ok "the web port is 8080 and the receiver port 8081"
else bad "the public ports are not web 8080 and receiver 8081"; fi
recv=$(grep '|kind: Deployment|' "$out/docs" | grep 'namespace: scrap-public|' || true)
# The token: a Secret volume mounted in the receiver alone, read as a file
if ! echo "$recv" | grep -Eq 'secretKeyRef|name: RECEIVER_TOKEN\|' &&
    echo "$recv" | grep -q 'name: RECEIVER_TOKEN_FILE|' &&
    [ "$(echo "$recv" | grep -o 'secretName: scrap-publish|' | wc -l)" = 1 ] &&
    [ "$(echo "$recv" | grep -o 'mountPath: /run/secrets/scrap-public|' | wc -l)" = 1 ] &&
    [ "$(echo "$recv" | grep -o 'readOnlyRootFilesystem: true' | wc -l)" = 2 ]; then
    ok "only the receiver mounts the token, as a file; both containers have read-only roots"
else bad "the token is an env var or reaches nginx, or a public container's root is writable"; fi
# By default the chart leaves the namespace (and the Secret in it) alone
if grep -q '|kind: Namespace|' "$out/docs"; then
    bad "public renders a Namespace without createNamespace"
else ok "public.createNamespace is off by default"; fi
if helm template scrap "$chart" -f "$chart/ci/public-values.yaml" --set public.createNamespace=true |
    awk '/^---/{d=""} {d=d $0 "|"} /pod-security.kubernetes.io\/enforce: restricted/{print d}' |
    grep -q 'kind: Namespace|'; then
    ok "createNamespace makes a Pod Security restricted namespace"
else bad "createNamespace does not make a restricted namespace"; fi
scrap_dep=$(grep '|kind: Deployment|' "$out/docs" | grep 'namespace: scrap-public|' -v || true)
if grep -A1 'name: SCRAP_PUBLISH_TO$' "$pub" | grep -q 'value: "http://scrap-receiver.scrap-public.svc:8081"' &&
    grep -A1 'name: SCRAP_PUBLISH_SITE$' "$pub" | grep -q 'value: "https://pages.example.org"' &&
    grep -A1 'name: SCRAP_PUBLISH_TOKEN_FILE$' "$pub" | grep -q 'value: /run/secrets/scrap-publish/token' &&
    ! grep -q 'name: SCRAP_PUBLISH_TOKEN$' "$pub" &&
    echo "$scrap_dep" | grep -q 'mountPath: /run/secrets/scrap-publish|' &&
    echo "$scrap_dep" | grep -q 'secretName: scrap-publish|'; then
    ok "scrap gets SCRAP_PUBLISH_TO, _SITE and the token as a mounted file"
else bad "scrap lacks SCRAP_PUBLISH_TO or _SITE, or its token is not a mounted file"; fi
# Public pages in the release namespace with networkPolicy off: no NetworkPolicy, and
# names that do not clash with scrap's own.
same=$(helm template scrap "$chart" --namespace scrap -f "$chart/ci/public-same-namespace-values.yaml")
names=$(echo "$same" | awk '/^kind: /{k=$2} /^  name: /{print k, $2}' | sort)
if ! echo "$same" | grep -q '^kind: NetworkPolicy$' &&
    [ -z "$(echo "$names" | uniq -d)" ] &&
    echo "$same" | grep -A1 'name: SCRAP_PUBLISH_TO$' | grep -q 'value: "http://scrap-receiver.scrap.svc:8081"'; then
    ok "public in the release namespace: no NetworkPolicy, no clashing names, the receiver's URL"
else bad "public in the release namespace: a NetworkPolicy, a clashing name or the wrong receiver URL"; fi

# authProxy: the main Ingress has the three auth annotations (with ingress.annotations),
# the open Ingress /mcp to scrap and /oauth2 to the ExternalName Service, without auth.
ap="$out/auth-proxy-checks"
helm template scrap "$chart" -f "$chart/ci/auth-proxy-values.yaml" \
    --set-string 'ingress.annotations.nginx\.ingress\.kubernetes\.io/auth-snippet=x' |
    awk 'function end_doc() { if (doc != "") print doc; doc = "" }
        /^---/ { end_doc(); next } { doc = doc $0 "|" } END { end_doc() }' >"$ap"
main=$(grep '|kind: Ingress|' "$ap" | grep '|  name: scrap|' || true)
open=$(grep '|kind: Ingress|' "$ap" | grep '|  name: scrap-open|' || true)
# shellcheck disable=SC2016 # $host and $escaped_request_uri are nginx's, not the shell's
if echo "$main" | grep -Fq '|    nginx.ingress.kubernetes.io/auth-url: http://oauth2-proxy.scrap.svc.cluster.local:80/oauth2/auth|' &&
    echo "$main" | grep -Fq '|    nginx.ingress.kubernetes.io/auth-signin: https://$host/oauth2/start?rd=$escaped_request_uri|' &&
    echo "$main" | grep -Fq '|    nginx.ingress.kubernetes.io/auth-response-headers: X-Auth-Request-Email,X-Auth-Request-Access-Token|' &&
    echo "$main" | grep -Fq '|    nginx.ingress.kubernetes.io/proxy-body-size: 50m|' &&
    echo "$main" | grep -Fq '|    nginx.ingress.kubernetes.io/proxy-buffer-size: 16k|' &&
    echo "$main" | grep -Fq '|          - path: /|' && ! echo "$main" | grep -q 'path: /mcp'; then
    ok "authProxy: the main Ingress asks oauth2-proxy, for the allowed email"
else bad "authProxy: the main Ingress lacks an auth annotation or has the wrong paths"; fi
if [ -n "$open" ] && ! echo "$open" | grep -q 'nginx.ingress.kubernetes.io/auth-' &&
    echo "$open" | grep -Fq '|    nginx.ingress.kubernetes.io/proxy-body-size: 50m|' &&
    echo "$open" | grep -Fq '|    nginx.ingress.kubernetes.io/proxy-buffer-size: 16k|' &&
    echo "$open" | grep -Fq '|          - path: /mcp|            pathType: Prefix|            backend:|              service:|                name: scrap|' &&
    echo "$open" | grep -Fq '|          - path: /oauth2|            pathType: Prefix|            backend:|              service:|                name: scrap-oauth2|' &&
    echo "$open" | grep -Fq '|  ingressClassName: nginx|' && echo "$open" | grep -Fq '|      - scrap-abc12345.example.org|' &&
    [ "$(echo "$open" | grep -o '            pathType' | wc -l)" = 2 ]; then
    ok "authProxy: the open Ingress has /mcp and /oauth2 only, and no auth annotations"
else bad "authProxy: the open Ingress has auth annotations or the wrong paths"; fi
if grep '|kind: Service|' "$ap" | grep '|  name: scrap-oauth2|' |
    grep -Fq '|  type: ExternalName|  externalName: oauth2-proxy.scrap.svc.cluster.local|'; then
    ok "authProxy: an ExternalName Service to the proxy"
else bad "authProxy: no ExternalName Service to the proxy"; fi
if grep -Fq '|            - name: SCRAP_IDENTITY_HEADER|              value: "X-Auth-Request-Email"|' "$ap" &&
    helm template scrap "$chart" -f "$chart/ci/auth-proxy-values.yaml" --set identityHeader=X-Mine |
    grep -A1 'name: SCRAP_IDENTITY_HEADER$' | grep -q 'value: "X-Mine"'; then
    ok "authProxy: identityHeader defaults to X-Auth-Request-Email"
else bad "authProxy: identityHeader is not X-Auth-Request-Email, or ignores identityHeader"; fi
# scrap checks the proxy's token itself (ADR 45): the Deployment has the issuer, the
# client and the lower-cased usernames; the CronJobs (no HTTP) do not.
deploy=$(grep '|kind: Deployment|' "$ap" | grep '|  name: scrap|' || true)
oidc_env='|            - name: SCRAP_OIDC_ISSUER|              value: "https://identity.example.org/realms/dls"|            - name: SCRAP_OIDC_CLIENT_ID|              value: "scrap"|            - name: SCRAP_ALLOWED_USERS|              value: "abc12345"|'
if echo "$deploy" | grep -Fq "$oidc_env" &&
    [ "$(grep -c 'SCRAP_OIDC_ISSUER' "$ap")" = 1 ] &&
    helm template scrap "$chart" -f "$chart/ci/auth-proxy-values.yaml" \
        --set 'authProxy.allowedUsers[0]=ABC12345' --set 'authProxy.allowedUsers[1]=xyz98765' |
    grep -A1 'name: SCRAP_ALLOWED_USERS$' | grep -Fq 'value: "abc12345,xyz98765"'; then
    ok "authProxy: the Deployment checks the proxy's token, for the lower-cased usernames"
else bad "authProxy: the Deployment lacks SCRAP_OIDC_* or SCRAP_ALLOWED_USERS, or a CronJob has them"; fi
if [ "$(helm template scrap "$chart" -f "$chart/ci/auth-proxy-values.yaml" \
    --set-string 'ingress.annotations.nginx\.ingress\.kubernetes\.io/proxy-buffer-size=32k' |
    grep -c 'nginx.ingress.kubernetes.io/proxy-buffer-size: 32k$')" = 2 ]; then
    ok "authProxy: an ingress.annotations proxy-buffer-size wins on both Ingresses"
else bad "authProxy: ingress.annotations' proxy-buffer-size is overridden"; fi
# ingress-nginx's annotation validation (DLS's) refuses an @ or % in the auth-url, so
# it has no query: the owner check is scrap's token check (SCRAP_ALLOWED_USERS).
if grep -o 'nginx.ingress.kubernetes.io/auth-url: [^|]*' "$ap" | grep -q '[?@%]'; then
    bad "authProxy: the auth-url has a query, an @ or a %"
else ok "authProxy: the auth-url has no query, @ or %"; fi
if helm template scrap "$chart" | grep -Eq 'ExternalName|-open$|auth-url|proxy-buffer-size|SCRAP_OIDC|SCRAP_ALLOWED_USERS'; then
    bad "authProxy renders while off"
else ok "authProxy is off by default"; fi

# The deprecated mode (litestream.enabled false, ADR 47): an upgrade with backups off
# (gc.enabled unset) renders, with no gc CronJob; with backups on, gc is a CronJob.
if helm template scrap "$chart" --set litestream.enabled=false --set backup.enabled=false | grep -q -- '-gc$'; then
    bad "backup off still renders a gc CronJob"
else ok "backup off renders without a gc CronJob"; fi
if helm template scrap "$chart" --set litestream.enabled=false | grep -q -- '-gc$'; then
    ok "litestream.enabled false renders the gc CronJob"
else bad "litestream.enabled false lacks the gc CronJob"; fi
# The scrap pod shows the purge date the gc CronJob keeps to, and "off" when it deletes
# nothing (no gc, or a counting one).
trash_days() { # helm-args...
    helm template scrap "$chart" "$@" | grep -A1 'name: SCRAP_TRASH_DAYS$' | sed -n 's/.*value: //p' | sort -u
}
if [ "$(trash_days)" = '"30"' ] && [ "$(trash_days -f "$chart/ci/gc-retention-values.yaml")" = '"60"' ] &&
    helm template scrap "$chart" -f "$chart/ci/gc-retention-values.yaml" --set litestream.enabled=false |
    grep -q -- '--trash-days "60" \\$' &&
    helm template scrap "$chart" -f "$chart/ci/gc-retention-values.yaml" |
    grep -A1 'name: SCRAP_SCHEDULE$' | grep -Fq -- '--trash-days \\\"60\\\"'; then
    ok "gc.trashDays sets SCRAP_TRASH_DAYS and gc's --trash-days"
else bad "gc.trashDays does not reach SCRAP_TRASH_DAYS or --trash-days"; fi
if [ "$(trash_days -f "$chart/ci/gc-dry-run-values.yaml")" = '"off"' ] &&
    [ "$(trash_days --set backup.enabled=false)" = '"off"' ]; then
    ok "SCRAP_TRASH_DAYS is off while gc deletes nothing"
else bad "SCRAP_TRASH_DAYS is not off while gc deletes nothing"; fi

# Backups in a hostPath: no backups claim, and every job that uses the backups
# (backup, backup-monthly, gc) mounts the directory instead.
hp=$(helm template scrap "$chart" -f "$chart/ci/backup-hostpath-values.yaml" --set litestream.enabled=false)
if ! echo "$hp" | grep -q -- '-backups$' && ! echo "$hp" | grep -q 'claimName: scrap-backups' &&
    [ "$(echo "$hp" | grep -c '^kind: CronJob$')" = 3 ] &&
    [ "$(echo "$hp" | grep -A1 '^              hostPath:$' |
        grep -c 'path: "/dls/science/users/abc12345/scrap"')" = 3 ]; then
    ok "backup.persistence.hostPath: no backups claim, all three CronJobs mount the directory"
else bad "backup.persistence.hostPath still makes a backups claim, or a CronJob lacks the directory"; fi

# Litestream (ADR 46), the default since ADR 47. Off (deprecated), nothing of it renders.
# On: the database on an emptyDir (the node's disk, not memory), the init order,
# Litestream a native sidecar, gc and the Claude passes in the pod not CronJobs, the
# backup jobs from the replica with the claim read only.
def_out=$(helm template scrap "$chart")
if echo "$def_out" | grep -q 'name: db-init$' && echo "$def_out" | grep -q 'name: jobs$' &&
    echo "$def_out" | grep -A1 'name: SCRAP_DB_PATH$' | grep -q 'value: /db/scrap.db' &&
    [ -z "$(echo "$def_out" | awk '/^---/{d=""} {d=d $0 "|"} /^  schedule: /{print d}' |
        grep -E '\|  name: scrap-(gc|enrich-related|enrich-topics)\|' | grep -v '|  suspend: true|')" ]; then
    ok "litestream is on by default, with gc in the pod"
else bad "the defaults are not Litestream"; fi
# The old mode's gc and Claude-pass CronJobs, for upgrades (ADR 47): the same names,
# suspended, running nothing but `true`, without the data claim.
stubs=$(echo "$def_out" | awk 'function end_doc() { if (doc != "") print doc; doc = "" }
    /^---/ { end_doc(); next } { doc = doc $0 "|" } END { end_doc() }' |
    grep '|kind: CronJob|' | grep -E '\|  name: scrap-(gc|enrich-related|enrich-topics)\|' || true)
if [ "$(echo "$stubs" | grep -c '|  suspend: true|')" = 3 ] &&
    [ "$(echo "$stubs" | grep -c 'command: \["true"\]|')" = 3 ] &&
    ! echo "$stubs" | grep -Eq 'claimName|volumes:|env:|"(gc|enrich)"'; then
    ok "litestream: the old gc and Claude-pass CronJobs are suspended stubs"
else bad "litestream: the old gc and Claude-pass CronJobs are not three suspended stubs"; fi
if helm template scrap "$chart" --set litestream.enabled=false -f "$chart/ci/ingest-values.yaml" |
    grep -Eiq 'litestream|SCRAP_DB_PATH|SCRAP_SCHEDULE|name: db-init|name: jobs'; then
    bad "litestream renders while off"
else ok "litestream.enabled false renders nothing of it"; fi
if [ "$(helm template scrap "$chart" --set litestream.enabled=false -f "$chart/ci/ingest-values.yaml" |
    grep -A3 '^kind: CronJob$' | grep -c '^  name: ')" = 5 ]; then
    ok "litestream.enabled false: backups, gc and the Claude passes are CronJobs"
else bad "litestream.enabled false: not the five CronJobs"; fi
ls_out=$(helm template scrap "$chart" -f "$chart/ci/litestream-values.yaml")
ls_docs="$out/litestream-docs"
echo "$ls_out" | awk 'function end_doc() { if (doc != "") print doc; doc = "" }
    /^---/ { end_doc(); next } { doc = doc $0 "|" } END { end_doc() }' >"$ls_docs"
ls_dep=$(grep '|kind: Deployment|' "$ls_docs")
ls_order=$(echo "$ls_out" | awk '/^kind: Deployment$/{d=1} /^---/{d=0} d && /^      volumes:$/{d=0} d && /^        - name: /{print $3}' | tr '\n' ' ')
if [ "$ls_order" = "litestream-tool db-init litestream scrap jobs " ]; then
    ok "litestream: the tool, db-init, Litestream, then scrap and jobs"
else bad "litestream: the containers are in the wrong order: $ls_order"; fi
if echo "$ls_dep" | grep -q '|          restartPolicy: Always|' &&
    [ "$(echo "$ls_dep" | grep -o 'restartPolicy: Always' | wc -l)" = 1 ]; then
    ok "litestream: a native sidecar, stopped after scrap"
else bad "litestream: not a native sidecar"; fi
if echo "$ls_dep" | grep -Fq '|        - name: db|          emptyDir:|            sizeLimit: 2Gi|' &&
    ! echo "$ls_dep" | grep -q 'medium:'; then
    ok "litestream: the database on a disk emptyDir"
else bad "litestream: the database is not on a disk emptyDir"; fi
if echo "$ls_dep" | grep -q 'terminationGracePeriodSeconds: 60|'; then
    ok "litestream: time for the last sync on shutdown"
else bad "litestream: no extra terminationGracePeriodSeconds"; fi
if echo "$ls_out" | grep -Eq 'image: litestream/litestream:[0-9]+\.[0-9]+\.[0-9]+@sha256:[0-9a-f]{64}$'; then
    ok "litestream: an exact version and digest"
else bad "litestream: the image is not pinned"; fi
ls_crons=$(grep '|kind: CronJob|' "$ls_docs" | grep -v '|  suspend: true|' |
    grep -o '|  name: [^|]*' | tr -s ' ' | tr '\n' ' ')
if [ "$ls_crons" = "| name: scrap-backup | name: scrap-backup-monthly " ]; then
    ok "litestream: gc and the Claude passes are not CronJobs"
else bad "litestream: CronJobs are not just the backups: $ls_crons"; fi
ls_sched=$(echo "$ls_out" | grep -A1 'name: SCRAP_SCHEDULE$' | grep 'value:')
if echo "$ls_sched" | grep -Fq '\"name\":\"gc\"' && echo "$ls_sched" | grep -q 'enrich-related' &&
    echo "$ls_sched" | grep -q 'enrich-topics' && echo "$ls_sched" | grep -Fq '30 4 * * *' &&
    echo "$ls_sched" | grep -Fq '41 3 * * *' && echo "$ls_sched" | grep -Fq '11 4 * * 0' &&
    echo "$ls_sched" | grep -Fq 'name COMPLETE -mmin -1560' && echo "$ls_sched" | grep -Fq 'counting only'; then
    ok "litestream: gc and the Claude passes on their schedules, gc still checking for a backup"
else bad "litestream: SCRAP_SCHEDULE lacks a job, a schedule or gc's backup check"; fi
# shellcheck disable=SC2016 # $SCRAP_LITESTREAM_REPLICA is the job's, not this shell's
if [ "$(echo "$ls_out" | grep -c -- '--from-replica "$SCRAP_LITESTREAM_REPLICA"')" = 2 ] &&
    ! grep '|kind: CronJob|' "$ls_docs" | grep -q 'SCRAP_DB_PATH' &&
    [ "$(grep '|kind: CronJob|' "$ls_docs" | grep -c '|                  mountPath: /data|                  readOnly: true|')" = 2 ] &&
    [ "$(grep '|kind: CronJob|' "$ls_docs" | grep -c 'podAffinity:')" = 2 ] &&
    [ "$(grep '|kind: CronJob|' "$ls_docs" | grep -c '|  suspend: true|')" = 3 ]; then
    ok "litestream: both backups from the replica, read only, on the scrap pod's node"
else bad "litestream: a backup job is not from the replica, read only and beside the pod"; fi
lhp=$(helm template scrap "$chart" -f "$chart/ci/litestream-hostpath-values.yaml")
if [ "$(echo "$lhp" | grep -A1 '^ *hostPath:$' | grep -c 'path: "/dls/science/users/abc12345/scrap"')" = 3 ]; then
    ok "litestream: the scrap pod and both backups mount a hostPath's backups"
else bad "litestream: something lacks the backups hostPath"; fi
if echo "$ls_dep" | grep -Fq '.replication-ok -mmin -5' &&
    echo "$ls_dep" | grep -Fq '|            - name: jobs-tmp|              mountPath: /tmp|'; then
    ok "litestream: jobs has a readiness probe on replication, and its own /tmp"
else bad "litestream: jobs lacks the replication probe or its own /tmp"; fi
if [ "$(echo "$ls_out" | grep -c 'name: SCRAP_DB_SIZE_LIMIT$')" = 2 ] &&
    [ "$(echo "$ls_out" | grep -c 'name: SCRAP_SCHEDULE$')" = 2 ]; then
    ok "litestream: db-init and jobs get the size limit and the schedule"
else bad "litestream: db-init or jobs lacks the size limit or the schedule"; fi
if helm template scrap "$chart" -f "$chart/ci/litestream-values.yaml" --set litestream.init.override=true |
    grep -A1 'name: SCRAP_DB_INIT_OVERRIDE$' | grep -q 'value: "on"' &&
    ! echo "$ls_out" | grep -q SCRAP_DB_INIT_OVERRIDE; then
    ok "litestream: the init's override is off unless set"
else bad "litestream: the init's override is wrong"; fi
# The jobs' metrics (#558): off by default, and nothing of them without Litestream. On:
# the port (not in the Service), its setting, the scrape annotations beside the user's,
# and a NetworkPolicy rule for the port.
if echo "$ls_out" | grep -Eq 'SCRAP_METRICS_PORT|name: metrics$|prometheus\.io/' ||
    helm template scrap "$chart" --set litestream.enabled=false --set litestream.jobs.metrics.enabled=true |
    grep -Eq 'SCRAP_METRICS_PORT|name: metrics$|prometheus\.io/|port: metrics'; then
    bad "litestream: the jobs' metrics render while off"
else ok "litestream: the jobs' metrics are off by default, and without Litestream"; fi
lm=$(helm template scrap "$chart" -f "$chart/ci/litestream-metrics-values.yaml")
if echo "$lm" | grep -A1 'name: SCRAP_METRICS_PORT$' | grep -q 'value: "9464"' &&
    echo "$lm" | grep -B1 'containerPort: 9464$' | grep -q 'name: metrics$' &&
    echo "$lm" | grep -q 'prometheus.io/port: "9464"$' &&
    echo "$lm" | grep -q 'prometheus.io/scrape: "true"$' &&
    echo "$lm" | grep -q 'example.com/owner: scrap$' &&
    echo "$lm" | grep -q -- '- port: metrics$' && echo "$lm" | grep -q -- '- port: http$' &&
    ! echo "$lm" | awk '/^kind: Service$/{s=1} /^---/{s=0} s' | grep -q 9464; then
    ok "litestream: the jobs' metrics on their own port, annotated, let through the NetworkPolicy"
else bad "litestream: the jobs' metrics lack their port, setting, annotations or NetworkPolicy rule"; fi
if helm template scrap "$chart" -f "$chart/ci/litestream-metrics-values.yaml" \
    --set litestream.jobs.metrics.podAnnotations=false | grep -q 'prometheus\.io/'; then
    bad "litestream: the scrape annotations are there although turned off"
else ok "litestream: the scrape annotations can be turned off"; fi

# By default both claims (data and backups) carry the annotations that keep them
# through helm uninstall and an Argo CD prune.
pvcs=$(helm template scrap "$chart" | awk '
    function end_doc() { if (kind == "PersistentVolumeClaim") { n++; if (keep && prune) good++ } }
    /^---/ { end_doc(); kind = ""; keep = 0; prune = 0; next }
    /^kind: / { kind = $2 }
    /^    helm\.sh\/resource-policy: keep$/ { keep = 1 }
    /^    argocd\.argoproj\.io\/sync-options: Prune=false$/ { prune = 1 }
    END { end_doc(); print n + 0, good + 0 }')
if [ "$pvcs" = "2 2" ]; then ok "data and backup claims carry the keep and Prune=false annotations"
else bad "data and backup claims lack the keep/Prune=false annotations (claims, protected: $pvcs)"; fi

# The chart may set only variables the app reads (the Settings table in
# docs/reference/api.md) or that deploy/scrap-backup reads, plus extraEnv.
repo=$(dirname "$chart")/..
docs=$repo/docs/reference/api.md
{
    helm template scrap "$chart" -f "$chart/ci/ingest-values.yaml"
    helm template scrap "$chart" -f "$chart/ci/mcp-auth-values.yaml"
    helm template scrap "$chart" -f "$chart/ci/public-values.yaml"
    helm template scrap "$chart" -f "$chart/ci/litestream-values.yaml" --set litestream.init.override=true
    helm template scrap "$chart" -f "$chart/ci/litestream-metrics-values.yaml"
} |
    grep -oE 'name: (SCRAP|ANTHROPIC)_[A-Z_]+' | sed 's/name: //' | sort -u >"$out/env"
while read -r var; do
    if grep -q "| \`$var\` |" "$docs"; then
        ok "env $var is an app setting"
    elif grep -q "\\\${$var:" "$repo/deploy/scrap-backup"; then
        ok "env $var is a scrap-backup setting"
    else
        bad "env $var is read by neither the app nor scrap-backup"
    fi
done <"$out/env"

exit "$fail"
