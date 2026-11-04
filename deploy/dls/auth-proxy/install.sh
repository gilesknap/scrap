#!/bin/sh
# Install or upgrade the central login proxy for DLS scrap installs: the upstream
# oauth2-proxy chart with values.yaml beside this script, in its own namespace.
#   module load argus
#   sh deploy/dls/auth-proxy/install.sh   # SCRAP_AUTH_NAMESPACE: the namespace (default scrap)
# The namespace must exist. The first run asks for the Keycloak client ID and secret and
# makes a cookie secret, into the Secret oauth2-proxy-keycloak. Later runs keep that
# Secret and only upgrade. See docs/how-to/run-the-dls-login-proxy.md.
set -eu

# The upstream chart, pinned. Bump it deliberately.
CHART_VERSION=10.7.1
REPO=https://oauth2-proxy.github.io/manifests

main() {
    here=$(cd "$(dirname "$0")" && pwd)
    ns=${SCRAP_AUTH_NAMESPACE:-scrap}
    secret=oauth2-proxy-keycloak

    tmp=
    trap 'rm -rf "$tmp"' EXIT
    # dash skips the EXIT trap when a signal kills it: exit, so the cleanup runs.
    trap 'exit 130' INT TERM HUP

    if ! kubectl -n "$ns" get secret "$secret" </dev/null >/dev/null 2>&1; then
        printf 'Keycloak client ID: ' >/dev/tty
        read -r client_id </dev/tty
        printf 'Keycloak client secret (input hidden): ' >/dev/tty
        # Ctrl-C at the prompt turns echo back on (the EXIT trap still cleans up).
        trap 'stty echo </dev/tty; echo >/dev/tty; exit 130' INT TERM HUP
        stty -echo </dev/tty
        read -r client_secret </dev/tty || client_secret=
        stty echo </dev/tty
        trap 'exit 130' INT TERM HUP
        echo >/dev/tty
        if [ -z "$client_id" ] || [ -z "$client_secret" ]; then
            echo "Both the client ID and the client secret are needed." >&2
            exit 1
        fi
        # Values go to kubectl as files in a private temp dir, never on the command line.
        tmp=$(mktemp -d)
        chmod 700 "$tmp"
        printf %s "$client_id" >"$tmp/client-id"
        printf %s "$client_secret" >"$tmp/client-secret"
        # 32 random bytes, URL-safe base64: what oauth2-proxy expects.
        head -c 32 /dev/urandom | base64 | tr -- '+/' '-_' | tr -d '\n' >"$tmp/cookie-secret"
        kubectl -n "$ns" create secret generic "$secret" </dev/null \
            --from-file=client-id="$tmp/client-id" \
            --from-file=client-secret="$tmp/client-secret" \
            --from-file=cookie-secret="$tmp/cookie-secret" >/dev/null
        rm -rf "$tmp"
        echo "Made Secret $secret in $ns."
    else
        echo "Secret $secret already exists in $ns: keeping it."
    fi

    helm upgrade --install oauth2-proxy oauth2-proxy --repo "$REPO" \
        --version "$CHART_VERSION" --namespace "$ns" -f "$here/values.yaml" \
        --wait --timeout 5m </dev/null
    echo "oauth2-proxy is at http://oauth2-proxy.$ns.svc.cluster.local/ inside the cluster."
}

main "$@"
