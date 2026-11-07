#!/bin/sh
# Install or upgrade the central login proxy for DLS scrap installs: the upstream
# oauth2-proxy chart with values.yaml beside this script, in its own namespace.
#   module load argus
#   sh deploy/dls/auth-proxy/install.sh   # SCRAP_AUTH_NAMESPACE: the namespace (default scrap)
# The namespace must exist. The first run asks for the Keycloak client ID and secret and
# makes a cookie secret, into the Secret oauth2-proxy-keycloak. Any run that finds no
# Secret oauth2-proxy-redis makes one with a random Redis password (the sessions are kept
# in a Redis beside the proxy). Later runs keep both Secrets and only upgrade. A run that
# makes either Secret also restarts Redis and the proxy, which read them only at start.
# See docs/how-to/run-the-dls-login-proxy.md.
set -eu

# The upstream chart, pinned. Bump it deliberately.
CHART_VERSION=10.7.1
REPO=https://oauth2-proxy.github.io/manifests

main() {
    here=$(cd "$(dirname "$0")" && pwd)
    ns=${SCRAP_AUTH_NAMESPACE:-scrap}
    secret=oauth2-proxy-keycloak
    redis_secret=oauth2-proxy-redis

    tmp=
    trap 'rm -rf "$tmp"' EXIT
    # dash skips the EXIT trap when a signal kills it: exit, so the cleanup runs.
    trap 'exit 130' INT TERM HUP

    made=
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
        made=yes
        echo "Made Secret $secret in $ns."
    else
        echo "Secret $secret already exists in $ns: keeping it."
    fi

    if ! kubectl -n "$ns" get secret "$redis_secret" </dev/null >/dev/null 2>&1; then
        tmp=$(mktemp -d)
        chmod 700 "$tmp"
        # 32 random bytes in hex: nothing in it needs quoting anywhere.
        head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' >"$tmp/redis-password"
        kubectl -n "$ns" create secret generic "$redis_secret" </dev/null \
            --from-file=redis-password="$tmp/redis-password" >/dev/null
        rm -rf "$tmp"
        made=yes
        echo "Made Secret $redis_secret in $ns."
    else
        echo "Secret $redis_secret already exists in $ns: keeping it."
    fi

    helm upgrade --install oauth2-proxy oauth2-proxy --repo "$REPO" \
        --version "$CHART_VERSION" --namespace "$ns" -f "$here/values.yaml" \
        --wait --timeout 5m </dev/null
    # The pods read the Secrets only at start, and an upgrade that changes nothing in
    # the chart leaves them running: restart them onto the new Secrets, Redis first.
    if [ -n "$made" ]; then
        for d in oauth2-proxy-redis oauth2-proxy; do
            if ! kubectl -n "$ns" rollout restart "deploy/$d" </dev/null ||
                ! kubectl -n "$ns" rollout status "deploy/$d" --timeout 5m </dev/null; then
                echo "The new Secret is in place but the $d pods did not restart: run" >&2
                echo "  kubectl -n $ns rollout restart deploy/oauth2-proxy-redis deploy/oauth2-proxy" >&2
                exit 1
            fi
        done
    fi
    echo "oauth2-proxy is at http://oauth2-proxy.$ns.svc.cluster.local/ inside the cluster."
}

main "$@"
