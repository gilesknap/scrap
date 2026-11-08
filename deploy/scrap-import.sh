#!/bin/sh
# Import a Markdown zip (a scrap export, an Obsidian vault) into scrap on Kubernetes,
# for a zip over the app's upload limit (SCRAP_MAX_UPLOAD_MB, 50 MB by default). It
# streams the zip into the running scrap pod and runs `scrap import` there, against
# the live database. kubectl only: no SSH to the nodes.
#
# A dry run unless --apply is given: the dry run writes nothing and lists every page,
# every problem and roughly what Claude would cost. Import is add-only: a page already
# in the store is skipped, never overwritten, and each new page is tagged
# import/<UTC date>. Claude is only called (and paid for) with --enrich or --photos.
# Ctrl-C stops the script and removes the zip, but an import already running in the
# pod may finish: that is safe, as it only adds, and a re-run skips the pages it did.
#
# Usage: scrap-import.sh [--apply] [--enrich] [--photos] [--] ZIP
#   --apply    import for real (default: a dry run)
#   --dry-run  accepted for clarity; it is the default
#   --enrich   queue the new text pages for Claude to tag and summarise
#   --photos   queue the new pages' photos for Claude to read (the dearer part)
#   --         end of options (for a zip whose name starts with -)
# Environment: SCRAP_NAMESPACE (default scrap), SCRAP_RELEASE (the Helm
#   release, default scrap).
set -eu

namespace=${SCRAP_NAMESPACE:-scrap}
release=${SCRAP_RELEASE:-scrap}
# The container's /tmp is an emptyDir with a 1Gi sizeLimit (tmp and jobs-tmp in the
# chart's deployment.yaml): leave headroom.
max_bytes=$((900 * 1024 * 1024))

usage() {
    sed -n '/^# Usage:/,/release, default scrap/s/^# \{0,1\}//p' "$0" >&2
    exit 2
}
die() {
    echo "scrap-import: $*" >&2
    exit 1
}

apply=false
enrich=
photos=
zip=
opts=true
while [ $# -gt 0 ]; do
    if ! $opts; then
        [ -z "$zip" ] || usage
        zip=$1
        shift
        continue
    fi
    case $1 in
    --) opts=false ;;
    --apply) apply=true ;;
    --dry-run) ;;
    --enrich) enrich=--enrich ;;
    --photos) photos=--photos ;;
    -h | --help) usage ;;
    -*)
        echo "scrap-import: unknown option $1" >&2
        usage
        ;;
    *)
        [ -z "$zip" ] || usage
        zip=$1
        ;;
    esac
    shift
done
[ -n "$zip" ] || usage
[ -f "$zip" ] || die "no such file: $zip"
size=$(wc -c <"$zip" | tr -d ' ')
if [ "$size" -gt "$max_bytes" ]; then
    die "$zip is $((size / 1024 / 1024)) MiB, over the pod's /tmp room" \
        "($((max_bytes / 1024 / 1024)) MiB); split it into smaller zips"
fi

# Exactly one Ready scrap pod, by the chart's selector labels (the CronJobs' pods have
# other names, so they never match), leaving out one being deleted (a rollout's old pod
# can still be Ready).
selector="app.kubernetes.io/instance=$release,app.kubernetes.io/name=scrap"
ready=$(kubectl -n "$namespace" get pods -l "$selector" -o \
    jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.conditions[?(@.type=="Ready")].status}{" "}{.metadata.deletionTimestamp}{"\n"}{end}' |
    awk '$2 == "True" && $3 == "" { print $1 }')
count=$(printf '%s' "$ready" | grep -c . || true)
if [ "$count" -ne 1 ]; then
    echo "scrap-import: want exactly one Ready scrap pod in namespace" \
        "$namespace ($selector), found $count" >&2
    kubectl -n "$namespace" get pods -l "$selector" >&2 || true
    exit 1
fi
pod=$ready

# With Litestream the chart's `jobs` container is where scrap commands run by hand go:
# it has the same SCRAP_DATA_DIR and SCRAP_DB_PATH as the server, its own /tmp and a
# larger memory limit. Without Litestream there is only `scrap`.
containers=$(kubectl -n "$namespace" get pod "$pod" -o jsonpath='{.spec.containers[*].name}')
container="scrap"
case " $containers " in *" jobs "*) container="jobs" ;; esac
kx() { kubectl -n "$namespace" exec "$pod" -c "$container" "$@"; }

# The chart sets SCRAP_DATA_DIR (and SCRAP_DB_PATH with Litestream): no --data-dir,
# which on its own would mean <data-dir>/scrap.db instead. Refuse to go on without an
# existing database, so a dry run cannot report on a wrong, empty store and an import
# cannot start a new one.
# shellcheck disable=SC2016 # expanded in the pod
db=$(kx -- sh -c 'db=${SCRAP_DB_PATH:-${SCRAP_DATA_DIR:-data}/scrap.db}; test -f "$db" && echo "$db"') ||
    die "no database found in $pod ($container)"
echo "pod $pod, container $container, database $db"

# The root filesystem is read-only; /tmp is the container's emptyDir.
remote=/tmp/scrap-import-$$-$(date +%s).zip
cleanup() {
    kx -- rm -f "$remote" || echo "scrap-import: could not remove $pod:$remote" >&2
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT TERM

echo "copying $zip ($size bytes) to $remote"
# Streamed with cat, so it needs no tar in the image (as kubectl cp would).
# shellcheck disable=SC2016 # expanded in the pod
kx -i -- sh -c 'cat >"$1"' sh "$remote" <"$zip"
copied=$(kx -- wc -c "$remote" | awk '{ print $1 }')
[ "$copied" = "$size" ] || die "copied $copied bytes of $size"

# $enrich and $photos are each empty or one fixed word: unquoted on purpose.
if $apply; then
    echo "importing (add-only: pages already here are skipped)"
    # shellcheck disable=SC2086
    kx -- scrap import $enrich $photos "$remote"
else
    # shellcheck disable=SC2086
    kx -- scrap import --dry-run $enrich $photos "$remote"
    echo
    echo "dry run: nothing was written. Run again with --apply to import."
fi
