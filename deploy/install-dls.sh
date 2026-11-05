#!/bin/sh
# Install scrap into your own namespace on the DLS argus Kubernetes cluster.
#   module load argus
#   curl -fsSL https://raw.githubusercontent.com/gilesknap/scrap/main/deploy/install-dls.sh | sh
# Safe to re-run: it upgrades the release, and never overwrites the Secret that holds
# your Claude API key, the /mcp bearer token and the public pages' upload token (it only
# adds that last one to a Secret made before it existed).
#
# The web app's login is DLS Keycloak, through the central oauth2-proxy that a scrap
# admin runs (deploy/dls/auth-proxy), letting in only your login; scrap checks the
# login's token itself, so a pod that calls its Service directly gets nowhere. /mcp
# keeps its bearer token. Public pages are on: the pages you make public are served on
# pages-$USER.diamond.ac.uk to anyone on the DLS network.
#
# scrap's database is on the pod's own disk, replicated continuously by Litestream to its
# volume, which is NFS here (ADR 46). An install from before that moves over by itself on
# upgrade, leaving the old file in place. If the node dies the last moments of writes are
# lost.
#
# Goes with the chart of the same release: an older SCRAP_VERSION needs that version's
# script, and this one before its release finds a chart without "litestream".
#
# Settings (environment, all optional; in a pipe they go after it: curl ... | SCRAP_LOGIN=off sh):
#   SCRAP_LOGIN            on (default), or off FOR TESTING ONLY: no login on the web app, so
#                          anyone on the DLS network, and any pod in the cluster, can read and
#                          change your pages. /mcp keeps its bearer token. Test data only.
#                          Re-run without it to turn the login on. Anything else is refused.
#   SCRAP_VERSION          chart version to install (default: the latest release)
#   SCRAP_CHART            chart to install (default: scrap's chart on ghcr.io)
#   SCRAP_NAMESPACE        namespace (default: the one `module load argus` selects, else $USER)
#   SCRAP_HOST             hostname (default: scrap-$USER.diamond.ac.uk: one level under
#                          diamond.ac.uk, so the ingress's *.diamond.ac.uk certificate covers it)
#   SCRAP_PAGES_HOST       public pages' hostname (default: pages-$USER.diamond.ac.uk)
#   SCRAP_EMAIL            your login's email address, the only one let in (not used with
#                          SCRAP_LOGIN=off; default: from
#                          your namespace's "email" label, first.last@diamond.ac.uk)
#   SCRAP_AUTH_NAMESPACE   the login proxy's namespace (default: scrap)
#   SCRAP_AUTH_SERVICE     the login proxy's in-cluster DNS name (default:
#                          oauth2-proxy.$SCRAP_AUTH_NAMESPACE.svc.cluster.local)
#   SCRAP_OIDC_ISSUER      the Keycloak realm whose login tokens scrap checks (default:
#                          https://identity.diamond.ac.uk/realms/dls)
#   SCRAP_OIDC_CLIENT_ID   the login proxy's Keycloak client (default: scrap)
#   SCRAP_INGRESS_CLASS    ingressClassName for the Ingress (default: nginx, argus's ingress)
#   SCRAP_BACKUP_DIR       where the nightly backups go (default: /dls/science/users/$USER/scrap,
#                          made here with mode 700 if new; every argus node mounts /dls/science).
#                          Empty keeps them on a claim in the cluster instead
#   SCRAP_SERVICE_TYPE     Service type (default ClusterIP; LoadBalancer gets an external IP,
#                          which bypasses any auth proxy: not recommended)
#   ANTHROPIC_API_KEY      your Claude API key (default: asked for; empty answer skips ingest)
set -eu

# An Ingress's values for HOST, indented under "ingress:".
ingress_values() {
    echo "  enabled: true"
    echo "  className: ${SCRAP_INGRESS_CLASS:-nginx}"
    echo "  hosts:"
    echo "    - $1"
    # No secretName: the controller's default (wildcard) certificate serves it. The
    # login's cookie is https only.
    echo "  tls:"
    echo "    - hosts:"
    echo "        - $1"
}

# What SCRAP_LOGIN=off means, up front and again in the summary.
login_off_warning() {
    cat <<EOF

WARNING: SCRAP_LOGIN=off: the web app has NO LOGIN. Anyone on the DLS network can read and
change the pages at https://$host/, and so can any pod in the cluster. Test data only.
To turn the login on, re-run this script without SCRAP_LOGIN=off.

EOF
}

# A failure leaves the web app's login as it was; turning it on has not happened yet.
login_unchanged() {
    echo "The web app stays as it was: if it had no login (SCRAP_LOGIN=off), it still has none," >&2
    echo "and anyone on the DLS network can read and change its pages." >&2
}

# All in a function that the last line runs: a download cut short runs nothing.
main() {
    # First, before anything is touched: a typo must never open an install.
    case ${SCRAP_LOGIN:-on} in
    on) login=on ;;
    off) login=off ;;
    *)
        echo "SCRAP_LOGIN must be on or off, not '$SCRAP_LOGIN'. Nothing was changed." >&2
        exit 1
        ;;
    esac
    version=${SCRAP_VERSION:-}
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
    pages_host=${SCRAP_PAGES_HOST:-pages-$user.diamond.ac.uk}
    auth_svc=${SCRAP_AUTH_SERVICE:-oauth2-proxy.${SCRAP_AUTH_NAMESPACE:-scrap}.svc.cluster.local}
    oidc_issuer=${SCRAP_OIDC_ISSUER:-https://identity.diamond.ac.uk/realms/dls}
    oidc_client=${SCRAP_OIDC_CLIENT_ID:-scrap}
    # The largest capture in MB: scrap's limit. nginx's body size is 1 MiB more, so a
    # file just over scrap's limit gets scrap's own error, not nginx's HTML 413.
    max_upload=50
    secret=scrap-secrets
    backup_dir=${SCRAP_BACKUP_DIR-/dls/science/users/$user/scrap}
    # scrap's pods run as you, so the backups in your directory are yours.
    uid=$(id -u)
    gid=$(id -g)

    # Temporary files, removed however the script ends.
    tmp=
    values=
    trap 'rm -rf "$tmp" "$values"' EXIT
    # dash skips the EXIT trap when a signal kills it: exit, so the cleanup runs.
    trap 'exit 130' INT TERM HUP

    what="the latest scrap"
    [ -z "$version" ] || what="scrap $version"
    echo "Installing $what into namespace $ns, for https://$host"

    if [ "$login" = off ]; then
        login_off_warning
    else
        # The web app lets in only this login (scrap checks it in the login's token). argus
        # labels your namespace with your email, first.last--at--diamond.ac.uk (a label value
        # cannot hold @). Lower case, as Keycloak's are.
        email=${SCRAP_EMAIL:-}
        if [ -z "$email" ]; then
            email=$(kubectl get namespace "$ns" -o jsonpath='{.metadata.labels.email}' </dev/null 2>/dev/null |
                sed 's/--at--/@/' || true)
        fi
        email=$(printf %s "$email" | tr '[:upper:]' '[:lower:]')
        case $email in
        "")
            echo "Cannot find your email address: namespace $ns has no \"email\" label you can read." >&2
            echo "Set SCRAP_EMAIL to your DLS email address (first.last@diamond.ac.uk) and re-run." >&2
            login_unchanged
            exit 1
            ;;
        *[!A-Za-z0-9._+@-]* | *@*@* | @* | *@) bad_email=yes ;;
        *@*) bad_email= ;;
        *) bad_email=yes ;;
        esac
        if [ -n "$bad_email" ]; then
            echo "Not an email address: $email. Set SCRAP_EMAIL to yours (first.last@diamond.ac.uk)." >&2
            login_unchanged
            exit 1
        fi
        echo "The web app's login will let in only $email."
    fi

    if [ -n "$backup_dir" ]; then
        case $backup_dir in
        /*) ;;
        *)
            echo "SCRAP_BACKUP_DIR must be an absolute path: $backup_dir" >&2
            exit 1
            ;;
        esac
        # Made private here; a directory that already exists keeps its mode.
        if [ -d "$backup_dir" ] && [ ! -w "$backup_dir" ]; then
            echo "You cannot write to $backup_dir, so the backups (run as you) would fail." >&2
            echo "Set SCRAP_BACKUP_DIR to a directory of yours, or to empty to keep them in the cluster." >&2
            exit 1
        elif [ -d "$backup_dir" ]; then
            echo "Backups go to $backup_dir."
        elif mkdir -p "$backup_dir" && chmod 700 "$backup_dir"; then
            echo "Backups go to $backup_dir (made, mode 700, yours)."
        else
            echo "Cannot make $backup_dir. Set SCRAP_BACKUP_DIR to a directory of yours" >&2
            echo "under /dls/science, or to empty to keep backups in the cluster." >&2
            exit 1
        fi
    fi

    # --- The Secret: API key, /mcp bearer token and the public pages' upload token.
    # Created once, never overwritten. ---
    new_token=
    if kubectl -n "$ns" get secret "$secret" </dev/null >/dev/null 2>&1; then
        if [ -z "$(kubectl -n "$ns" get secret "$secret" -o jsonpath='{.data.SCRAP_MCP_TOKEN}' </dev/null 2>/dev/null)" ]; then
            echo "Secret $secret in $ns has no SCRAP_MCP_TOKEN, which scrap needs. Delete it" >&2
            echo "  kubectl -n $ns delete secret $secret" >&2
            echo "and re-run: the installer makes a new one, asking for your API key again." >&2
            exit 1
        fi
        echo "Secret $secret already exists in $ns: keeping your API key and token."
        # Made before public pages: add their upload token, changing nothing else.
        if [ -z "$(kubectl -n "$ns" get secret "$secret" -o jsonpath='{.data.SCRAP_PUBLISH_TOKEN}' </dev/null 2>/dev/null)" ]; then
            tmp=$(mktemp -d)
            chmod 700 "$tmp"
            {
                printf '{"data":{"SCRAP_PUBLISH_TOKEN":"'
                head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | base64 | tr -d '\n'
                printf '"}}'
            } >"$tmp/patch.json"
            kubectl -n "$ns" patch secret "$secret" --type merge \
                --patch-file "$tmp/patch.json" </dev/null >/dev/null
            rm -rf "$tmp"
            echo "Added the public pages' upload token to $secret."
        fi
    else
        key=${ANTHROPIC_API_KEY:-}
        if [ -z "$key" ] && ( : </dev/tty ) 2>/dev/null; then
            printf 'Claude API key for ingest (input hidden; Enter to skip): ' >/dev/tty
            # Ctrl-C at the prompt turns echo back on (the EXIT trap still cleans up).
            trap 'stty echo </dev/tty 2>/dev/null; echo >/dev/tty; exit 130' INT TERM HUP
            stty -echo </dev/tty 2>/dev/null || true
            read -r key </dev/tty || key=
            stty echo </dev/tty 2>/dev/null || true
            trap 'exit 130' INT TERM HUP
            echo >/dev/tty
        fi
        new_token=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
        # Values go to kubectl as files in a private temp dir, never on the command line.
        tmp=$(mktemp -d)
        chmod 700 "$tmp"
        printf %s "$new_token" >"$tmp/SCRAP_MCP_TOKEN"
        head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' >"$tmp/SCRAP_PUBLISH_TOKEN"
        set -- --from-file=SCRAP_MCP_TOKEN="$tmp/SCRAP_MCP_TOKEN" \
            --from-file=SCRAP_PUBLISH_TOKEN="$tmp/SCRAP_PUBLISH_TOKEN"
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
        echo "    value: https://$host"
        echo "podSecurityContext:"
        echo "  runAsUser: $uid"
        echo "  runAsGroup: $gid"
        echo "  fsGroup: $gid"
        # argus caps a container's CPU limit at 10 times its request, and its default
        # limit is 1 CPU: the jobs request 50m, so give them a limit that fits.
        # The backup jobs restore the database to their own disk first: argus's largest
        # (and its default is 1Gi).
        echo "backup:"
        echo "  resources: {limits: {cpu: 500m, ephemeral-storage: 2Gi}}"
        if [ -n "$backup_dir" ]; then
            echo "  persistence:"
            echo "    hostPath: $backup_dir"
        fi
        # The database off NFS, onto the pod's disk, replicated to the volume (ADR 46). gc
        # and the Claude passes then run in the pod. An existing /data/scrap.db comes across.
        echo "litestream:"
        echo "  enabled: true"
        echo "  resources: {limits: {cpu: 500m}}"
        echo "  init: {resources: {limits: {cpu: 500m}}}"
        # gc and the Claude passes, which restore nothing but share the pod's disk.
        echo "  jobs: {resources: {limits: {cpu: 500m, ephemeral-storage: 2Gi}}}"
        echo "service:"
        echo "  type: ${SCRAP_SERVICE_TYPE:-ClusterIP}"
        echo "maxUploadMB: $max_upload"
        echo "ingress:"
        ingress_values "$host"
        echo "  annotations:"
        echo "    nginx.ingress.kubernetes.io/proxy-body-size: \"$((max_upload + 1))m\""
        if [ "$login" = on ]; then
            # The web app's login: DLS Keycloak through the central oauth2-proxy, for you alone.
            echo "authProxy:"
            echo "  enabled: true"
            echo "  service: $auth_svc"
            echo "  allowedEmails:"
            echo "    - \"$email\""
            # scrap checks the proxy's Keycloak token on each request: from this realm, for
            # this client, for your email.
            echo "  oidc:"
            echo "    issuer: \"$oidc_issuer\""
            echo "    clientId: \"$oidc_client\""
        fi
        # Public pages, in this namespace, so they share the Secret. argus lets no user
        # make a NetworkPolicy. The pods request 10m of CPU: a limit argus accepts.
        echo "public:"
        echo "  enabled: true"
        echo "  namespace: $ns"
        echo "  site: https://$pages_host"
        echo "  tokenSecret:"
        echo "    name: $secret"
        echo "    key: SCRAP_PUBLISH_TOKEN"
        echo "  ingress:"
        ingress_values "$pages_host" | sed 's/^/  /'
        echo "  networkPolicy:"
        echo "    enabled: false"
        echo "  resources:"
        echo "    web: {limits: {cpu: 100m}}"
        echo "    receiver: {limits: {cpu: 100m}}"
    } >"$values"

    # No --version: Helm picks the newest release (it skips pre-releases).
    if ! helm upgrade --install scrap "$CHART" ${version:+--version "$version"} \
        --namespace "$ns" -f "$values" --wait --timeout 5m </dev/null; then
        echo "Helm failed; fix the cause above and re-run this script." >&2
        echo "If the scrap pod is stuck in Init, its database is the question:" >&2
        echo "  kubectl -n $ns logs deploy/scrap -c db-init" >&2
        echo "If it said additional properties 'litestream' not allowed, that chart is older" >&2
        echo "than this script: use the script from that version (SCRAP_VERSION), or its release." >&2
        login_unchanged
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

    # The version Helm installed, as "scrap-1.5.0" in its one-line JSON; empty if not found.
    installed=$(helm -n "$ns" list --filter '^scrap$' -o json </dev/null 2>/dev/null |
        sed -n 's/.*"chart":"scrap-\([^"]*\)".*/\1/p' || true)

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

    if [ "$login" = on ]; then
        who="DLS login, for $email only"
    else
        who="NO LOGIN: anyone on the DLS network"
    fi
    # shellcheck disable=SC2016 # quotes inside a heredoc are literal: $ns does expand
    cat <<EOF

scrap ${installed:+$installed }is running in namespace $ns.

  External IP: ${extip:-none yet: see 'kubectl -n $ns get svc scrap'}
  Service IP (inside the cluster): ${ip:-unknown}
  Web app:  https://$host/   ($who)
  MCP:      https://$host/mcp   (needs the bearer token)
  Pages:    https://$pages_host/   (the pages you make public; anyone on the DLS network)

EOF
    if [ "$login" = on ]; then
        cat <<EOF
  The login keeps the web app from the network, and scrap checks the login's token
  itself: a pod that calls its Service directly without your login gets 401 (and
  /mcp needs the bearer token).

EOF
    else
        login_off_warning
    fi
    cat <<EOF
  The database is on the pod's own disk, replicated continuously by Litestream to your
  volume. If the node dies, the last moments of writes are lost.

Next steps
EOF
    missing=
    for name in "$host" "$pages_host"; do
        getent hosts "$name" </dev/null >/dev/null 2>&1 || missing="$missing $name"
    done
    if [ -z "$missing" ]; then
        echo "  1. $host and $pages_host already resolve: nothing to ask for."
    else
        cat <<EOF
  1. Raise a request at
         https://jira.diamond.ac.uk/servicedesk/customer/portal/2/create/156
     asking for these names to be set up on the argus ingress for namespace $ns:
EOF
        for name in $missing; do
            echo "         $name"
        done
        cat <<EOF
     Until they exist, check scrap is up from this shell:
         kubectl -n $ns port-forward svc/scrap 8000:80
     then open http://127.0.0.1:8000/healthz. The web app needs the login, so it and
     the phone app wait for the DNS names.
EOF
    fi
    if [ "$login" = on ]; then
        cat <<EOF
  2. Ask a scrap admin to add your login address
         https://$host/oauth2/callback
     to the Keycloak client. Until it is added, logging in to the web app fails;
     /mcp does not need it.
  3. On your phone, join the DLS VPN, then open https://$host/, log in with your DLS
     account (the login page shows the first time), and install the app.
EOF
    else
        cat <<EOF
  2. On your phone, join the DLS VPN, then open https://$host/ and install the app.
EOF
    fi
    if [ -n "$new_token" ]; then
        cat <<EOF

Your MCP bearer token (shown once; keep it in a password manager):

  $new_token

To connect Claude Code, follow "Connect Claude Code" in the tutorial:
  https://gilesknap.github.io/scrap/main/tutorials/install-dls.html
EOF
    else
        cat <<EOF

Your MCP bearer token is unchanged. To show it again:
  kubectl -n $ns get secret $secret -o jsonpath='{.data.SCRAP_MCP_TOKEN}' | base64 -d; echo
EOF
    fi
}

main "$@"
