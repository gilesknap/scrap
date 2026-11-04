#!/bin/sh
# Install scrap into your own namespace on the DLS argus Kubernetes cluster.
#   module load argus
#   curl -fsSL https://raw.githubusercontent.com/gilesknap/scrap/main/deploy/install-dls.sh | sh
# Safe to re-run: it upgrades the release, and never overwrites the Secret that holds
# your Claude API key and the /mcp bearer token.
#
# Settings (environment, all optional):
#   SCRAP_VERSION          chart version to install (default: the pin below)
#   SCRAP_NAMESPACE        namespace (default: the one `module load argus` selects, else $USER)
#   SCRAP_HOST             hostname (default: scrap.$USER.diamond.ac.uk)
#   SCRAP_SCHEME           https (default) or http: the scheme the hostname is served on
#   SCRAP_INGRESS_CLASS    ingressClassName for the Ingress (default: the cluster's default)
#   SCRAP_INGRESS_NAMESPACE  namespace of the ingress controller; when set, a NetworkPolicy
#                          admits only that namespace to scrap
#   SCRAP_SERVICE_TYPE     Service type (default ClusterIP; LoadBalancer gets an external IP,
#                          which bypasses any auth proxy: not recommended)
#   ANTHROPIC_API_KEY      your Claude API key (default: asked for; empty answer skips ingest)
set -eu

# The pinned release. Bump it when a new scrap release should reach DLS users.
VERSION=${SCRAP_VERSION:-1.4.0}
CHART=${SCRAP_CHART:-oci://ghcr.io/gilesknap/charts/scrap}

for tool in kubectl helm; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "$tool not found. Run 'module load argus' first, then re-run this." >&2
        exit 1
    fi
done

user=${USER:-$(id -un)}
ns=${SCRAP_NAMESPACE:-$(kubectl config view --minify --output 'jsonpath={..namespace}' 2>/dev/null || true)}
ns=${ns:-$user}
host=${SCRAP_HOST:-scrap.$user.diamond.ac.uk}
scheme=${SCRAP_SCHEME:-https}
secret=scrap-secrets

echo "Installing scrap $VERSION into namespace $ns, for https://$host"

# --- The Secret: API key and /mcp bearer token. Created once, never overwritten. ---
new_token=
if kubectl -n "$ns" get secret "$secret" >/dev/null 2>&1; then
    echo "Secret $secret already exists in $ns: keeping your API key and token."
else
    key=${ANTHROPIC_API_KEY:-}
    if [ -z "$key" ] && ( : </dev/tty ) 2>/dev/null; then
        printf 'Claude API key for ingest (input hidden; Enter to skip): ' >/dev/tty
        stty -echo </dev/tty 2>/dev/null || true
        read -r key </dev/tty || key=
        stty echo </dev/tty 2>/dev/null || true
        echo >/dev/tty
    fi
    new_token=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
    # Values go to kubectl on stdin / a private temp dir, never the command line.
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    chmod 700 "$tmp"
    printf %s "$new_token" >"$tmp/SCRAP_MCP_TOKEN"
    set -- --from-file=SCRAP_MCP_TOKEN="$tmp/SCRAP_MCP_TOKEN"
    if [ -n "$key" ]; then
        printf %s "$key" >"$tmp/ANTHROPIC_API_KEY"
        set -- "$@" --from-file=ANTHROPIC_API_KEY="$tmp/ANTHROPIC_API_KEY"
    fi
    kubectl -n "$ns" create secret generic "$secret" "$@" >/dev/null
    rm -rf "$tmp"
    if [ -n "$key" ]; then ingest=yes; else ingest=no; fi
fi
# Ingest follows the Secret: on if it holds the API key (also on a re-run).
if kubectl -n "$ns" get secret "$secret" -o jsonpath='{.data.ANTHROPIC_API_KEY}' 2>/dev/null |
    grep -q .; then
    ingest=yes
else
    ingest=no
fi

# --- The values (no secrets in them) ---
values=$(mktemp)
trap 'rm -f "$values"' EXIT
{
    echo "ingest:"
    echo "  enabled: $([ "$ingest" = yes ] && echo true || echo false)"
    echo "  existingSecret: $secret"
    echo "mcp:"
    echo "  tokenSecret:"
    echo "    name: $secret"
    echo "    key: SCRAP_MCP_TOKEN"
    echo "extraEnv:"
    echo "  - name: SCRAP_PUBLIC_URL"
    echo "    value: $scheme://$host"
    echo "service:"
    echo "  type: ${SCRAP_SERVICE_TYPE:-ClusterIP}"
    echo "ingress:"
    echo "  enabled: true"
    [ -z "${SCRAP_INGRESS_CLASS:-}" ] || echo "  className: ${SCRAP_INGRESS_CLASS}"
    echo "  hosts:"
    echo "    - $host"
    if [ -n "${SCRAP_INGRESS_NAMESPACE:-}" ]; then
        echo "networkPolicy:"
        echo "  enabled: true"
        echo "  from:"
        echo "    - namespaceSelector:"
        echo "        matchLabels:"
        echo "          kubernetes.io/metadata.name: ${SCRAP_INGRESS_NAMESPACE}"
    fi
} >"$values"

helm upgrade --install scrap "$CHART" --version "$VERSION" \
    --namespace "$ns" -f "$values" --wait --timeout 5m
rm -f "$values"

ip=$(kubectl -n "$ns" get svc scrap -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)
extip=
if [ "${SCRAP_SERVICE_TYPE:-ClusterIP}" = LoadBalancer ]; then
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
        extip=$(kubectl -n "$ns" get svc scrap \
            -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
        [ -z "$extip" ] || break
        sleep 5
    done
fi

cat <<EOF

scrap is running in namespace $ns.

  External IP: ${extip:-none yet: see 'kubectl -n $ns get svc scrap'}
  Service IP (inside the cluster): ${ip:-unknown}
  Web app:  $scheme://$host/
  MCP:      $scheme://$host/mcp   (needs the bearer token)

Next steps
  1. Open a cloud team ticket asking for the DNS name
         $host
     to point at the argus ingress for namespace $ns.
  2. Until it exists, look at scrap from this shell:
         kubectl -n $ns port-forward svc/scrap 8000:80
     then open http://127.0.0.1:8000/. /mcp and the phone app need the DNS name.
  3. On your phone, join the DLS VPN, then open $scheme://$host/ and install the app.
EOF
if [ -n "$new_token" ]; then
    cat <<EOF

Your MCP bearer token (shown once; keep it in a password manager):

  $new_token

Claude Code: claude mcp add --transport http scrap $scheme://$host/mcp \\
    --header "Authorization: Bearer <the token above>"
EOF
else
    cat <<EOF

Your MCP bearer token is unchanged. To show it again:
  kubectl -n $ns get secret $secret -o jsonpath='{.data.SCRAP_MCP_TOKEN}' | base64 -d; echo
EOF
fi
