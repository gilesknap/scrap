{{/* litestream.* (ADR 46): the database on an emptyDir, replicated to the data volume. */}}
{{- define "scrap.litestreamImage" -}}
{{ .Values.litestream.image.repository }}:{{ .Values.litestream.image.tag }}{{ with .Values.litestream.image.digest }}@{{ . }}{{ end }}
{{- end }}

{{/* Copies the litestream program where the scrap image can run it. Call with
(dict "ctx" . "resources" ...). */}}
{{- define "scrap.litestreamTool" -}}
- name: litestream-tool
  image: {{ include "scrap.litestreamImage" .ctx }}
  imagePullPolicy: {{ .ctx.Values.litestream.image.pullPolicy }}
  command: ["cp", "/usr/local/bin/litestream", "/tools/litestream"]
  securityContext:
    {{- toYaml .ctx.Values.securityContext | nindent 4 }}
  resources:
    {{- toYaml .resources | nindent 4 }}
  volumeMounts:
    - name: tools
      mountPath: /tools
{{- end }}

{{/* The Deployment's init containers: the tool, the database put in place (or the pod
stops here), then Litestream as a native sidecar, so it starts before scrap and stops
after it. */}}
{{- define "scrap.litestreamInit" -}}
{{- if semverCompare "<1.29-0" .Capabilities.KubeVersion.Version }}
{{- fail "litestream.enabled needs Kubernetes 1.29 or newer (native sidecar containers)" }}
{{- end }}
{{- include "scrap.litestreamTool" (dict "ctx" . "resources" .Values.litestream.resources) }}
- name: db-init
  image: {{ include "scrap.image" . }}
  imagePullPolicy: {{ .Values.image.pullPolicy }}
  args: ["db-init"]
  env:
    - name: SCRAP_DATA_DIR
      value: /data
    - name: SCRAP_DB_PATH
      value: /db/scrap.db
    - name: SCRAP_LITESTREAM_REPLICA
      value: /data/litestream
    - name: SCRAP_LITESTREAM_BIN
      value: /tools/litestream
    {{- if .Values.backup.enabled }}
    - name: SCRAP_BACKUPS
      value: /backups
    {{- end }}
    {{- if .Values.litestream.init.override }}
    - name: SCRAP_DB_INIT_OVERRIDE
      value: "on"
    {{- end }}
  securityContext:
    {{- toYaml .Values.securityContext | nindent 4 }}
  resources:
    {{- toYaml .Values.litestream.init.resources | nindent 4 }}
  volumeMounts:
    - name: data
      mountPath: /data
    - name: db
      mountPath: /db
    - name: tools
      mountPath: /tools
    - name: tmp
      mountPath: /tmp
    {{- if .Values.backup.enabled }}
    - name: backups
      mountPath: /backups
      readOnly: true
    {{- end }}
- name: litestream
  image: {{ include "scrap.litestreamImage" . }}
  imagePullPolicy: {{ .Values.litestream.image.pullPolicy }}
  # A native sidecar: runs alongside the containers, and is stopped after them.
  restartPolicy: Always
  command:
    - /bin/sh
    - -ec
    - |
      cat >/tools/litestream.yml <<'EOF'
      # Snapshots shorten a restore. Retention is Litestream's default.
      snapshot:
        interval: 6h
        retention: 24h
      # Within the pod's extra 30s of terminationGracePeriodSeconds.
      shutdown-sync-timeout: 25s
      dbs:
        - path: /db/scrap.db
          replica:
            type: file
            path: /data/litestream
      EOF
      exec litestream replicate -config /tools/litestream.yml
  securityContext:
    {{- toYaml .Values.securityContext | nindent 4 }}
  resources:
    {{- toYaml .Values.litestream.resources | nindent 4 }}
  volumeMounts:
    - name: data
      mountPath: /data
    - name: db
      mountPath: /db
    - name: tools
      mountPath: /tools
{{- end }}

{{/* gc's script, in its CronJob or in scrap schedule. Deleting is on only with a grace
period: with none, a file an upload is still writing could be deleted. Otherwise the job
only counts. */}}
{{- define "scrap.gcScript" -}}
{{- $delete := and .Values.gc.delete (gt (float64 .Values.gc.graceHours) 0.0) -}}
{{- if .Values.backup.enabled }}
# Not during a backup run (the backup job takes the same lock).
exec 9>"$SCRAP_BACKUPS/.lock"
flock 9
{{- end }}
{{- if $delete }}
{{- if .Values.gc.requireBackup }}
recent=$(find "$SCRAP_BACKUPS" -mindepth 2 -maxdepth 2 -type f -name COMPLETE -mmin -1560 \
    -path '*/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z/COMPLETE' |
    head -n 1)
{{- else }}
recent=unchecked
{{- end }}
mode=--delete
if [ -z "$recent" ]; then
    echo "No backup in the last 26 hours: counting only, deleting nothing." >&2
    mode=--dry-run
fi
scrap gc "$mode" --grace-hours {{ .Values.gc.graceHours | toString | quote }} \
    --run-days {{ .Values.gc.runDays | toString | quote }} \
    --trash-days {{ .Values.gc.trashDays | toString | quote }} \
    --job-days {{ .Values.gc.jobDays | toString | quote }}
[ -n "$recent" ] || exit 1
{{- else }}
# Counting only (gc.delete is off, or gc.graceHours is 0): see values.yaml.
scrap gc --dry-run --grace-hours {{ .Values.gc.graceHours | toString | quote }} \
    --run-days {{ .Values.gc.runDays | toString | quote }} \
    --trash-days {{ .Values.gc.trashDays | toString | quote }} \
    --job-days {{ .Values.gc.jobDays | toString | quote }}
{{- end }}
{{- end }}

{{/* The jobs that need the live database, for scrap schedule: gc and the Claude passes
on the schedules their CronJobs would have. Exactly as their CronJobs decide whether to
exist, and with their deadlines. */}}
{{- define "scrap.scheduledJobs" -}}
{{- $jobs := list }}
{{- if include "scrap.gcEnabled" . }}
{{- if and .Values.gc.requireBackup (not .Values.backup.enabled) }}
{{- fail "gc.enabled=true needs backup.enabled (gc deletes only after a recent backup); leave gc.enabled unset or false, or gc.requireBackup=false to delete without one" }}
{{- end }}
{{- $jobs = append $jobs (dict "name" "gc" "schedule" .Values.gc.schedule "timeZone" .Values.gc.timeZone "timeoutSeconds" 3600 "command" (list "/bin/sh" "-ec" (include "scrap.gcScript" . | trim))) }}
{{- end }}
{{- if and .Values.enrichRelated.enabled .Values.ingest.enabled }}
{{- $jobs = append $jobs (dict "name" "enrich-related" "schedule" .Values.enrichRelated.schedule "timeZone" .Values.enrichRelated.timeZone "timeoutSeconds" 14400 "command" (list "scrap" "enrich" "--related")) }}
{{- end }}
{{- if and .Values.enrichTopics.enabled .Values.ingest.enabled }}
{{- $jobs = append $jobs (dict "name" "enrich-topics" "schedule" .Values.enrichTopics.schedule "timeZone" .Values.enrichTopics.timeZone "timeoutSeconds" 3600 "command" (list "scrap" "enrich" "--topics")) }}
{{- end }}
{{- $jobs | toJson }}
{{- end }}

{{- define "scrap.jobsContainer" -}}
- name: jobs
  image: {{ include "scrap.image" . }}
  imagePullPolicy: {{ .Values.image.pullPolicy }}
  args: ["schedule"]
  env:
    {{- include "scrap.appEnv" . | nindent 4 }}
    {{- if .Values.backup.enabled }}
    - name: SCRAP_BACKUPS
      value: /backups
    {{- end }}
    - name: SCRAP_SCHEDULE
      value: {{ include "scrap.scheduledJobs" . | quote }}
  {{- with .Values.extraEnvFrom }}
  envFrom:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  securityContext:
    {{- toYaml .Values.securityContext | nindent 4 }}
  resources:
    {{- toYaml .Values.litestream.jobs.resources | nindent 4 }}
  volumeMounts:
    - name: data
      mountPath: /data
    - name: db
      mountPath: /db
    - name: tmp
      mountPath: /tmp
    {{- if .Values.backup.enabled }}
    # Read-write only for the lock file; gc reads the COMPLETE markers here.
    - name: backups
      mountPath: /backups
    {{- end }}
{{- end }}
