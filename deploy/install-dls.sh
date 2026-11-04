#!/bin/sh
# Install scrap into your own namespace on the DLS argus Kubernetes cluster.
#   module load argus
#   curl -fsSL https://raw.githubusercontent.com/gilesknap/scrap/main/deploy/install-dls.sh | sh
# Safe to re-run: it upgrades the release, and never overwrites the Secret that holds
# your Claude API key and the /mcp bearer token.
#
# Settings (environment, all optional):
#   SCRAP_VERSION          chart version to install (default: the pin below)
#   SCRAP_CHART            chart to install (default: scrap's chart on ghcr.io)
#   SCRAP_NAMESPACE        namespace (default: the one `module load argus` selects, else $USER)
#   SCRAP_HOST             hostname (default: scrap-$USER.diamond.ac.uk: one level under
#                          diamond.ac.uk, so the ingress's *.diamond.ac.uk certificate covers it)
#   SCRAP_SCHEME           https (default) or http: the scheme the hostname is served on
#   SCRAP_INGRESS_CLASS    ingressClassName for the Ingress (default: nginx, argus's ingress)
#   SCRAP_BACKUP_DIR       where the nightly backups go (default: /dls/science/users/$USER/scrap,
#                          made here with mode 700 if new; every argus node mounts /dls/science).
#                          Empty keeps them on a claim in the cluster instead
#   SCRAP_SERVICE_TYPE     Service type (default ClusterIP; LoadBalancer gets an external IP,
#                          which bypasses any auth proxy: not recommended)
#   ANTHROPIC_API_KEY      your Claude API key (default: asked for; empty answer skips ingest)
set -eu

# All in a function that the last line runs: a download cut short runs nothing.
main() {
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
    ns=${SCRAP_NAMESPACE:-$(kubectl config view --minify --output 'jsonpath={..namespace}' </dev/null 2>/dev/null || true)}
    ns=${ns:-$user}
    host=${SCRAP_HOST:-scrap-$user.diamond.ac.uk}
    scheme=${SCRAP_SCHEME:-https}
    secret=scrap-secrets
    backup_dir=${SCRAP_BACKUP_DIR-/dls/science/users/$user/scrap}
    # scrap's pods run as you, so the backups in your directory are yours.
    uid=$(id -u)
    gid=$(id -g)

    # Temporary files, removed however the script ends.
    tmp=
    values=
    trap 'rm -rf "$tmp" "$values"' EXIT

    echo "Installing scrap $VERSION into namespace $ns, for $scheme://$host"

    if [ -n "$backup_dir" ]; then
        case $backup_dir in
        /*) ;;
        *)
            echo "SCRAP_BACKUP_DIR must be an absolute path: $backup_dir" >&2
            exit 1
            ;;
        esac
        # Made private here; a directory that already exists keeps its mode.
        if [ -d "$backup_dir" ]; then
            echo "Backups go to $backup_dir."
        elif mkdir -p "$backup_dir" && chmod 700 "$backup_dir"; then
            echo "Backups go to $backup_dir (made, mode 700, yours)."
        else
            echo "Cannot make $backup_dir. Set SCRAP_BACKUP_DIR to a directory of yours" >&2
            echo "under /dls/science, or to empty to keep backups in the cluster." >&2
            exit 1
        fi
    fi

    # --- The Secret: API key and /mcp bearer token. Created once, never overwritten. ---
    new_token=
    if kubectl -n "$ns" get secret "$secret" </dev/null >/dev/null 2>&1; then
        echo "Secret $secret already exists in $ns: keeping your API key and token."
    else
        key=${ANTHROPIC_API_KEY:-}
        if [ -z "$key" ] && ( : </dev/tty ) 2>/dev/null; then
            printf 'Claude API key for ingest (input hidden; Enter to skip): ' >/dev/tty
            # Ctrl-C at the prompt turns echo back on (the EXIT trap still cleans up).
            trap 'stty echo </dev/tty 2>/dev/null; echo >/dev/tty; exit 130' INT TERM
            stty -echo </dev/tty 2>/dev/null || true
            read -r key </dev/tty || key=
            stty echo </dev/tty 2>/dev/null || true
            trap - INT TERM
            echo >/dev/tty
        fi
        new_token=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
        # Values go to kubectl as files in a private temp dir, never on the command line.
        tmp=$(mktemp -d)
        chmod 700 "$tmp"
        printf %s "$new_token" >"$tmp/SCRAP_MCP_TOKEN"
        set -- --from-file=SCRAP_MCP_TOKEN="$tmp/SCRAP_MCP_TOKEN"
        if [ -n "$key" ]; then
            printf %s "$key" >"$tmp/ANTHROPIC_API_KEY"
            set -- "$@" --from-file=ANTHROPIC_API_KEY="$tmp/ANTHROPIC_API_KEY"
        fi
        kubectl -n "$ns" create secret generic "$secret" "$@" </dev/null >/dev/null
        rm -rf "$tmp"
    fi
    # Ingest follows the Secret: on if it holds the API key (also on a re-run).
    if kubectl -n "$ns" get secret "$secret" -o jsonpath='{.data.ANTHROPIC_API_KEY}' </dev/null 2>/dev/null |
        grep -q .; then
        ingest=yes
    else
        ingest=no
    fi

    # --- The values (no secrets in them) ---
    values=$(mktemp)
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
        echo "podSecurityContext:"
        echo "  runAsUser: $uid"
        echo "  runAsGroup: $gid"
        echo "  fsGroup: $gid"
        # argus caps a container's CPU limit at 10 times its request, and its default
        # limit is 1 CPU: the jobs request 50m, so give them a limit that fits.
        echo "backup:"
        echo "  resources: {limits: {cpu: 500m}}"
        if [ -n "$backup_dir" ]; then
            echo "  persistence:"
            echo "    hostPath: $backup_dir"
        fi
        for job in gc enrichRelated enrichTopics; do
            echo "$job:"
            echo "  resources: {limits: {cpu: 500m}}"
        done
        echo "service:"
        echo "  type: ${SCRAP_SERVICE_TYPE:-ClusterIP}"
        echo "ingress:"
        echo "  enabled: true"
        echo "  className: ${SCRAP_INGRESS_CLASS:-nginx}"
        echo "  hosts:"
        echo "    - $host"
        if [ "$scheme" = https ]; then
            # No secretName: the controller's default (wildcard) certificate serves it.
            echo "  tls:"
            echo "    - hosts:"
            echo "        - $host"
        fi
    } >"$values"

    if ! helm upgrade --install scrap "$CHART" --version "$VERSION" \
        --namespace "$ns" -f "$values" --wait --timeout 5m </dev/null; then
        echo "Helm failed; fix the cause above and re-run this script." >&2
        if [ -n "$new_token" ]; then
            # The Secret is kept, so a re-run will not show this token again.
            cat >&2 <<EOF

Your MCP bearer token (shown once; keep it in a password manager):

  $new_token
EOF
        fi
        exit 1
    fi
    rm -f "$values"

    ip=$(kubectl -n "$ns" get svc scrap -o jsonpath='{.spec.clusterIP}' </dev/null 2>/dev/null || true)
    extip=
    if [ "${SCRAP_SERVICE_TYPE:-ClusterIP}" = LoadBalancer ]; then
        for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
            extip=$(kubectl -n "$ns" get svc scrap \
                -o jsonpath='{.status.loadBalancer.ingress[0].ip}' </dev/null 2>/dev/null || true)
            [ -z "$extip" ] || break
            sleep 5
        done
    fi

    # shellcheck disable=SC2016 # quotes inside a heredoc are literal: $ns does expand
    cat <<EOF

scrap is running in namespace $ns.

  External IP: ${extip:-none yet: see 'kubectl -n $ns get svc scrap'}
  Service IP (inside the cluster): ${ip:-unknown}
  Web app:  $scheme://$host/
  MCP:      $scheme://$host/mcp   (needs the bearer token)

Next steps
EOF
    if getent hosts "$host" </dev/null >/dev/null 2>&1; then
        echo "  1. $host already resolves: nothing to ask for."
    else
        cat <<EOF
  1. Open a cloud team ticket asking for the DNS name
         $host
     to point at the argus ingress (ingress-nginx) for namespace $ns.
     Until it exists, look at scrap from this shell:
         kubectl -n $ns port-forward svc/scrap 8000:80
     then open http://127.0.0.1:8000/. /mcp and the phone app need the DNS name.
EOF
    fi
    cat <<EOF
  2. On your phone, join the DLS VPN, then open $scheme://$host/ and install the app.
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
}

main "$@"
