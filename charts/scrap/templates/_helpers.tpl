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

{{/* Pod-level settings shared by the Deployment and the backup CronJob. */}}
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
