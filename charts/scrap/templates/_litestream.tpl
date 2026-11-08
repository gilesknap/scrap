{{/* litestream.* (ADR 46): the database on an emptyDir, replicated to the data volume. */}}
{{/* Where the database is, and its replica on the data volume. Nowhere else. */}}
{{- define "scrap.litestreamDb" -}}
/db/scrap.db
{{- end }}

{{- define "scrap.litestreamReplica" -}}
/data/litestream
{{- end }}

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
{{- /* Chart.yaml's kubeVersion (>=1.29, ADR 47) refuses first, so this is not reached
now; it stays in case that minimum moves. */ -}}
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
      value: {{ include "scrap.litestreamDb" . }}
    - name: SCRAP_LITESTREAM_REPLICA
      value: {{ include "scrap.litestreamReplica" . }}
    - name: SCRAP_LITESTREAM_BIN
      value: /tools/litestream
    - name: SCRAP_DB_SIZE_LIMIT
      value: {{ .Values.litestream.sizeLimit | quote }}
    # Checked here, so a bad schedule stops the rollout.
    - name: SCRAP_SCHEDULE
      value: {{ include "scrap.scheduledJobs" . | quote }}
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
    - name: jobs-tmp
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
      # How long the last sync at shutdown retries (Litestream's default is 30s): within
      # the 30s the pod's terminationGracePeriodSeconds gains for it.
      shutdown-sync-timeout: 25s
      dbs:
        - path: {{ include "scrap.litestreamDb" . }}
          replica:
            type: file
            path: {{ include "scrap.litestreamReplica" . }}
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
{{- $jobs = append $jobs (dict "name" "gc" "schedule" .Values.gc.schedule "timeZone" .Values.gc.timeZone "timeoutSeconds" 3600 "command" (list "/bin/sh" "-ec" (include "scrap.gcScript" . | trim))) }}
{{- end }}
{{- if and .Values.enrichRelated.enabled .Values.ingest.enabled }}
{{- $jobs = append $jobs (dict "name" "enrich-related" "schedule" .Values.enrichRelated.schedule "timeZone" .Values.enrichRelated.timeZone "timeoutSeconds" 14400 "pausable" true "command" (list "scrap" "enrich" "--related")) }}
{{- end }}
{{- if and .Values.enrichTopics.enabled .Values.ingest.enabled }}
{{- $jobs = append $jobs (dict "name" "enrich-topics" "schedule" .Values.enrichTopics.schedule "timeZone" .Values.enrichTopics.timeZone "timeoutSeconds" 3600 "pausable" true "command" (list "scrap" "enrich" "--topics")) }}
{{- end }}
{{- $jobs | toJson }}
{{- end }}

{{/* The pod's annotations: podAnnotations, and with the jobs' metrics on, Prometheus's
scrape annotations beneath them. */}}
{{- define "scrap.podAnnotations" -}}
{{- $annotations := deepCopy (.Values.podAnnotations | default dict) }}
{{- $metrics := .Values.litestream.jobs.metrics }}
{{- if and .Values.litestream.enabled $metrics.enabled $metrics.podAnnotations }}
{{- $annotations = merge $annotations (dict "prometheus.io/scrape" "true" "prometheus.io/port" ($metrics.port | toString) "prometheus.io/path" "/metrics") }}
{{- end }}
{{- with $annotations }}
{{- toYaml . }}
{{- end }}
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
    - name: SCRAP_DB_SIZE_LIMIT
      value: {{ .Values.litestream.sizeLimit | quote }}
    - name: SCRAP_SCHEDULE
      value: {{ include "scrap.scheduledJobs" . | quote }}
    {{- if .Values.litestream.jobs.metrics.enabled }}
    - name: SCRAP_METRICS_PORT
      value: {{ .Values.litestream.jobs.metrics.port | quote }}
    {{- end }}
  {{- with .Values.extraEnvFrom }}
  envFrom:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- if .Values.litestream.jobs.metrics.enabled }}
  # scrap schedule's own metrics (scrap.metrics): not in the Service
  ports:
    - name: metrics
      containerPort: {{ .Values.litestream.jobs.metrics.port }}
  {{- end }}
  # scrap schedule keeps this file young while the replica takes writes, and removes it
  # when it does not: the pod then leaves its Service, so scrap stops taking writes it
  # cannot protect (ADR 46).
  readinessProbe:
    exec:
      command:
        - /bin/sh
        - -c
        - test -n "$(find {{ dir (include "scrap.litestreamDb" .) }}/.replication-ok -mmin -5 2>/dev/null)"
    periodSeconds: 30
    timeoutSeconds: 5
    failureThreshold: 2
  securityContext:
    {{- toYaml .Values.securityContext | nindent 4 }}
  resources:
    {{- toYaml .Values.litestream.jobs.resources | nindent 4 }}
  volumeMounts:
    - name: data
      mountPath: /data
    - name: db
      mountPath: /db
    # Its own, as the jobs must not fill scrap's; db-init uses it first.
    - name: jobs-tmp
      mountPath: /tmp
    {{- if .Values.backup.enabled }}
    # Read-write only for the lock file; gc reads the COMPLETE markers here.
    - name: backups
      mountPath: /backups
    {{- end }}
{{- end }}
