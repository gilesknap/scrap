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
    if [ "$name" = long-names ]; then release=a-release-name-of-fifty-three-characters-the-maximum; fi
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
    if grep -A1 -E 'name: (ANTHROPIC_API_KEY|SCRAP_NOTIFY_URL)$' "$m" | grep -Eq 'value:'; then
        bad "$name: a secret setting rendered as a plain value"
    fi
    if ! { grep -q '^  replicas: 1$' "$m" && grep -q 'type: Recreate' "$m"; }; then
        bad "$name: not one replica with Recreate"
    fi
    # Kubernetes name limits: a CronJob's name 52, other names and label values 63
    # (PVC names may be longer).
    long=$(awk '/^kind: /{kind=$2} /^  name: /{n=$2; if ((kind=="CronJob" && length(n)>52) || (kind!="PersistentVolumeClaim" && length(n)>63)) print kind, n}
        /^ +(app\.kubernetes\.io|helm\.sh)\/[a-z-]+: /{v=$2; gsub(/"/,"",v); if (length(v)>63) print "label", v}' "$m")
    if [ -n "$long" ]; then bad "$name: too long: $(echo "$long" | tr "\n" " ")"; fi
    ok "$name: rendered, no secrets, one replica, names fit"
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
expect_refused "a non-numeric budget" --set ingest.budgetDayUSD=lots
expect_refused "a negative budget" --set ingest.budgetDayUSD=-1

# The chart may set only variables the app reads (the Settings table in
# docs/reference/api.md) or that deploy/scrap-backup reads, plus extraEnv.
repo=$(dirname "$chart")/..
docs=$repo/docs/reference/api.md
helm template scrap "$chart" -f "$chart/ci/ingest-values.yaml" |
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
