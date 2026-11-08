#!/bin/sh
# shellcheck disable=SC2329 # the checks are called through check
# Tests for scrap-import.sh with a stub kubectl (no cluster needed): the pod's /tmp is
# a temp folder, so the streamed zip, its size check and its removal can be seen.
# Run: ./deploy/test-scrap-import.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
fail=0
check() { # check NAME CONDITION-COMMAND...
    name=$1; shift
    if "$@"; then echo "ok   $name"; else echo "FAIL $name"; fail=1; fi
}

# kubectl: records each call in $tmp/kubectl.calls. The Ready pods are STUB_PODS (lines
# of "name Ready-status [deletionTimestamp]"), the pod's containers STUB_CONTAINERS. In exec, the pod's /tmp
# is $tmp/pod/tmp; the database check fails with STUB_NODB, the copy stops short with
# STUB_SHORT, and scrap import (recorded in $tmp/import.calls, with whether the zip was
# there) fails with STUB_IMPORT_FAIL, or hangs up on the script with STUB_IMPORT_HUP.
cat >"$tmp/bin/kubectl" <<STUB
#!/bin/sh
echo "\$*" >>"$tmp/kubectl.calls"
case "\$*" in
  *"get pods"*jsonpath*) printf '%b' "\${STUB_PODS-scrap-abc True\\\\n}"; exit 0 ;;
  *"get pods"*) echo "NAME READY"; exit 0 ;;
  *"get pod "*) printf '%s' "\${STUB_CONTAINERS-scrap jobs}"; exit 0 ;;
esac
while [ \$# -gt 0 ] && [ "\$1" != -- ]; do shift; done
shift
case "\$*" in
  "sh -c cat >"*)
    if [ -n "\${STUB_SHORT:-}" ]; then head -c 3 >"$tmp/pod\$5"; else cat >"$tmp/pod\$5"; fi
    exit 0 ;;
  "sh -c "*SCRAP_DB_PATH*) [ -z "\${STUB_NODB:-}" ] || exit 1; echo /db/scrap.db; exit 0 ;;
  "wc -c "*) wc -c <"$tmp/pod\$3" | tr -d ' '; exit 0 ;;
  "rm -f "*) rm -f "$tmp/pod\$3"; echo "\$3" >>"$tmp/removed"; exit 0 ;;
  "scrap import "*)
    for a in "\$@"; do last=\$a; done
    if [ -f "$tmp/pod\$last" ]; then here=zip-there; else here=zip-missing; fi
    echo "\$* \$here" >>"$tmp/import.calls"
    [ -z "\${STUB_IMPORT_FAIL:-}" ] || exit 1
    [ -z "\${STUB_IMPORT_HUP:-}" ] || { kill -HUP "\$PPID"; exit 0; }
    echo "import output"; exit 0 ;;
esac
echo "stub kubectl: unexpected \$*" >&2
exit 3
STUB
chmod +x "$tmp/bin/kubectl"

printf 'PK fake zip bytes\n' >"$tmp/small.zip"
code=0
run() { # run [ARGS...]: the script on a fresh pod, its exit code in $code
    rm -rf "$tmp/pod" "$tmp/kubectl.calls" "$tmp/import.calls" "$tmp/removed"
    mkdir -p "$tmp/pod/tmp"
    code=0
    (cd "${RUN_DIR:-.}" && PATH="$tmp/bin:$PATH" exec "$here/scrap-import.sh" "$@") >"$tmp/out" 2>&1 || code=$?
}
out_has() { grep -q -- "$1" "$tmp/out"; }
calls_have() { grep -q -- "$1" "$tmp/kubectl.calls"; }
imported() { grep -q -- "$1" "$tmp/import.calls"; }
no_import() { [ ! -e "$tmp/import.calls" ]; }
cleaned() { [ -s "$tmp/removed" ] && [ -z "$(ls -A "$tmp/pod/tmp")" ]; }

# A dry run by default, in the jobs container, with the zip streamed in whole
run "$tmp/small.zip"
check "dry run succeeds" [ "$code" = 0 ]
check "dry run by default" imported "^scrap import --dry-run /tmp/scrap-import-.*\.zip zip-there$"
check "says nothing was written" out_has "dry run: nothing was written"
check "picks the jobs container" calls_have "exec scrap-abc -c jobs"
check "namespace and selector default to scrap" calls_have "-n scrap get pods -l app.kubernetes.io/instance=scrap,app.kubernetes.io/name=scrap"
check "streams with kubectl exec -i" calls_have "exec scrap-abc -c jobs -i -- sh -c"
check "names the pod and database" out_has "pod scrap-abc, container jobs, database /db/scrap.db"
check "zip removed after a dry run" cleaned

# --apply runs the import; --enrich and --photos pass through; namespace and release
run --apply --enrich --photos "$tmp/small.zip"
check "apply succeeds" [ "$code" = 0 ]
check "apply imports for real with the flags" imported "^scrap import --enrich --photos /tmp/scrap-import-.*\.zip zip-there$"
check "zip removed after an import" cleaned
run --dry-run --photos "$tmp/small.zip"
check "--dry-run keeps the dry run, with a flag" imported "^scrap import --dry-run --photos /tmp/"
SCRAP_NAMESPACE=me SCRAP_RELEASE=notes run "$tmp/small.zip"
check "SCRAP_NAMESPACE and SCRAP_RELEASE are used" calls_have "-n me get pods -l app.kubernetes.io/instance=notes,app.kubernetes.io/name=scrap"

# Without Litestream there is only the scrap container
STUB_CONTAINERS=scrap run "$tmp/small.zip"
check "picks scrap without a jobs container" calls_have "exec scrap-abc -c scrap"
check "never asks for jobs then" sh -c "! grep -q -- '-c jobs' '$tmp/kubectl.calls'"

# Exactly one Ready pod
STUB_PODS='' run "$tmp/small.zip"
check "no pod: refused" [ "$code" = 1 ]
check "no pod: says found 0" out_has "found 0"
check "no pod: nothing imported" no_import
STUB_PODS='scrap-abc False\n' run "$tmp/small.zip"
check "a pod not Ready: refused" out_has "found 0"
STUB_PODS='scrap-abc True\nscrap-def True\n' run "$tmp/small.zip"
check "two Ready pods: refused" [ "$code" = 1 ]
check "two Ready pods: says found 2" out_has "found 2"
check "two Ready pods: nothing imported" no_import
STUB_PODS='scrap-abc False\nscrap-def True\n' run "$tmp/small.zip"
check "one Ready of two: uses it" calls_have "exec scrap-def -c jobs"
STUB_PODS='scrap-old True 2026-11-08T10:00:00Z\nscrap-new True\n' run "$tmp/small.zip"
check "a Ready pod being deleted: left out" [ "$code" = 0 ]
check "a Ready pod being deleted: the other is used" calls_have "exec scrap-new -c jobs"
STUB_PODS='scrap-old True 2026-11-08T10:00:00Z\n' run "$tmp/small.zip"
check "only a pod being deleted: refused" out_has "found 0"

# No database: refused before anything is copied
STUB_NODB=1 run "$tmp/small.zip"
check "no database: refused" [ "$code" = 1 ]
check "no database: says so" out_has "no database found in scrap-abc (jobs)"
check "no database: nothing copied or imported" sh -c "no() { ! grep -q -- \"\$1\" '$tmp/kubectl.calls'; }; no 'cat >' && [ ! -e '$tmp/import.calls' ]"

# A zip over the /tmp room (900 MiB): refused before kubectl is called (a sparse file)
dd if=/dev/null of="$tmp/big.zip" bs=1 seek=$((900 * 1024 * 1024 + 1)) 2>/dev/null
run "$tmp/big.zip"
check "oversize zip: refused" [ "$code" = 1 ]
check "oversize zip: says split it" out_has "split it into smaller zips"
check "oversize zip: no kubectl" [ ! -e "$tmp/kubectl.calls" ]
dd if=/dev/null of="$tmp/edge.zip" bs=1 seek=$((900 * 1024 * 1024)) 2>/dev/null
run "$tmp/edge.zip"
check "zip at the limit: allowed" [ "$code" = 0 ]

# A copy that stops short: refused, not imported, and cleaned up
STUB_SHORT=1 run --apply "$tmp/small.zip"
check "short copy: refused" [ "$code" = 1 ]
check "short copy: says so" out_has "copied 3 bytes of 18"
check "short copy: nothing imported" no_import
check "short copy: zip removed" cleaned

# An import that fails: its failure is the exit code, and the zip still goes
STUB_IMPORT_FAIL=1 run --apply "$tmp/small.zip"
check "failed import: fails" [ "$code" != 0 ]
check "failed import: zip removed" cleaned

# A closed terminal (SIGHUP) mid-import: the zip still goes
STUB_IMPORT_HUP=1 run --apply "$tmp/small.zip"
check "hang-up: exits 129" [ "$code" = 129 ]
check "hang-up: zip removed" cleaned

# Arguments
run
check "no zip: usage" [ "$code" = 2 ]
check "usage text" out_has "Usage: scrap-import.sh"
run --bogus "$tmp/small.zip"
check "unknown option: usage" [ "$code" = 2 ]
check "unknown option: named" out_has "unknown option --bogus"
run "$tmp/small.zip" "$tmp/small.zip"
check "two zips: usage" [ "$code" = 2 ]
cp "$tmp/small.zip" "$tmp/-x.zip"
RUN_DIR=$tmp run --apply -- -x.zip
check "-- ends the options: a zip named -x.zip" imported "^scrap import /tmp/scrap-import-.*\.zip zip-there$"
RUN_DIR=$tmp run -- -x.zip --apply
check "-- ends the options: no option after it" [ "$code" = 2 ]
run "$tmp/missing.zip"
check "missing zip: refused" [ "$code" = 1 ]
check "missing zip: says so" out_has "no such file"

exit $fail
