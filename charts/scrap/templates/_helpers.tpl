{{- define "scrap.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "scrap.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "scrap.selectorLabels" -}}
app.kubernetes.io/name: {{ include "scrap.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "scrap.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{ include "scrap.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "scrap.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "scrap.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "scrap.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/* The CronJob's name: at most 52 characters (the API server's limit, so
that its Jobs' names fit). A longer fullname is cut and given a short hash. */}}
{{- define "scrap.backupName" -}}
{{- $full := include "scrap.fullname" . }}
{{- if le (len $full) 45 }}
{{- printf "%s-backup" $full }}
{{- else }}
{{- printf "%s-%s-backup" ($full | trunc 38 | trimSuffix "-") ($full | sha256sum | trunc 6) }}
{{- end }}
{{- end }}

{{/* The backup pod's name label: at most 63 characters. */}}
{{- define "scrap.backupLabel" -}}
{{- printf "%s-backup" (include "scrap.name" . | trunc 56 | trimSuffix "-") }}
{{- end }}

{{- define "scrap.dataClaim" -}}
{{- .Values.persistence.existingClaim | default (printf "%s-data" (include "scrap.fullname" .)) }}
{{- end }}

{{- define "scrap.backupClaim" -}}
{{- .Values.backup.persistence.existingClaim | default (printf "%s-backups" (include "scrap.fullname" .)) }}
{{- end }}

{{/* A CronJob's name for a suffix such as "-gc": at most 52 characters, cut and
given a short hash like scrap.backupName. Call with (dict "ctx" . "suffix" "-gc"). */}}
{{- define "scrap.cronName" -}}
{{- $full := include "scrap.fullname" .ctx }}
{{- $room := sub 52 (len .suffix) | int }}
{{- if le (len $full) $room }}
{{- printf "%s%s" $full .suffix }}
{{- else }}
{{- printf "%s-%s%s" ($full | trunc (sub $room 7 | int) | trimSuffix "-") ($full | sha256sum | trunc 6) .suffix }}
{{- end }}
{{- end }}

{{/* The pod's name label for such a CronJob: at most 63 characters. */}}
{{- define "scrap.cronLabel" -}}
{{- printf "%s%s" (include "scrap.name" .ctx | trunc (sub 63 (len .suffix) | int) | trimSuffix "-") .suffix }}
{{- end }}

{{/* The data claim is ReadWriteOnce, and SQLite needs the server's host (its
write-ahead log is shared memory): a CronJob's pod runs beside the scrap pod. */}}
{{- define "scrap.sameNodeAffinity" -}}
podAffinity:
  requiredDuringSchedulingIgnoredDuringExecution:
    - topologyKey: kubernetes.io/hostname
      labelSelector:
        matchLabels:
          {{- include "scrap.selectorLabels" . | nindent 10 }}
{{- end }}

{{/* The app's own settings, as the Deployment sets them. A CronJob that runs a
scrap command which calls Claude (enrich --related, --topics) needs the same. */}}
{{- define "scrap.appEnv" -}}
- name: SCRAP_DATA_DIR
  value: /data
- name: SCRAP_MAX_UPLOAD_MB
  value: {{ .Values.maxUploadMB | quote }}
- name: SCRAP_INGEST
  value: {{ ternary "on" "off" .Values.ingest.enabled | quote }}
# How long a page stays in the trash, as the server shows it: the gc CronJob's
# trashDays when it deletes, else off (nothing purges the trash)
- name: SCRAP_TRASH_DAYS
  value: {{ include "scrap.trashDays" . | quote }}
{{- with .Values.identityHeader }}
- name: SCRAP_IDENTITY_HEADER
  value: {{ . | quote }}
{{- end }}
{{- with .Values.mcp.tokenSecret.name }}
- name: SCRAP_MCP_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ . }}
      key: {{ required "mcp.tokenSecret.key is empty" $.Values.mcp.tokenSecret.key }}
{{- end }}
{{- if .Values.ingest.enabled }}
- name: ANTHROPIC_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.ingest.existingSecret }}
      key: {{ .Values.ingest.apiKeyKey }}
{{- with .Values.ingest.notifyUrlKey }}
- name: SCRAP_NOTIFY_URL
  valueFrom:
    secretKeyRef:
      name: {{ $.Values.ingest.existingSecret }}
      key: {{ . }}
{{- end }}
{{- with .Values.ingest.visionModel }}
- name: SCRAP_VISION_MODEL
  value: {{ . | quote }}
{{- end }}
{{- $budget := toString .Values.ingest.budgetDayUSD }}
{{- if ne $budget "" }}
- name: SCRAP_BUDGET_DAY_USD
  value: {{ $budget | quote }}
{{- end }}
{{- end }}
{{- with .Values.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/* Pod-level settings shared by the Deployment and the CronJobs. */}}
{{- define "scrap.podCommon" -}}
serviceAccountName: {{ include "scrap.serviceAccountName" . }}
automountServiceAccountToken: false
{{- with .Values.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
securityContext:
  {{- toYaml .Values.podSecurityContext | nindent 2 }}
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}

{{/* "true" when the gc CronJob is wanted, else empty: gc.enabled, or when that is
unset (null) whether backup.enabled, so a release with backups off still renders. */}}
{{/* SCRAP_TRASH_DAYS: gc.trashDays while the gc CronJob deletes (as gc-cronjob.yaml
decides), else off. */}}
{{- define "scrap.trashDays" -}}
{{- if and (include "scrap.gcEnabled" .) .Values.gc.delete (gt (float64 .Values.gc.graceHours) 0.0) -}}
{{ .Values.gc.trashDays | toString }}
{{- else -}}
off
{{- end -}}
{{- end }}

{{- define "scrap.gcEnabled" -}}
{{- if kindIs "invalid" .Values.gc.enabled -}}
{{- if .Values.backup.enabled }}true{{ end -}}
{{- else if .Values.gc.enabled }}true{{ end -}}
{{- end }}
