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

{{/* The backups volume's source: backup.persistence.hostPath when set, else the claim. */}}
{{- define "scrap.backupVolume" -}}
{{- with .Values.backup.persistence.hostPath -}}
hostPath:
  path: {{ . | quote }}
  type: Directory
{{- else -}}
persistentVolumeClaim:
  claimName: {{ include "scrap.backupClaim" . }}
{{- end }}
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
{{- if .Values.litestream.enabled }}
- name: SCRAP_DB_PATH
  value: {{ include "scrap.litestreamDb" . }}
- name: SCRAP_LITESTREAM_REPLICA
  value: {{ include "scrap.litestreamReplica" . }}
{{- end }}
- name: SCRAP_MAX_UPLOAD_MB
  value: {{ .Values.maxUploadMB | quote }}
- name: SCRAP_INGEST
  value: {{ ternary "on" "off" .Values.ingest.enabled | quote }}
# How long a page stays in the trash, as the server shows it: the gc CronJob's
# trashDays when it deletes, else off (nothing purges the trash)
- name: SCRAP_TRASH_DAYS
  value: {{ include "scrap.trashDays" . | quote }}
{{- with .Values.identityHeader | default (ternary "X-Auth-Request-Email" "" .Values.authProxy.enabled) }}
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

{{/* SCRAP_TRASH_DAYS: gc.trashDays while the gc CronJob deletes (as gc-cronjob.yaml
decides), else off. */}}
{{- define "scrap.trashDays" -}}
{{- if and (include "scrap.gcEnabled" .) .Values.gc.delete (gt (float64 .Values.gc.graceHours) 0.0) -}}
{{ .Values.gc.trashDays | toString }}
{{- else -}}
off
{{- end -}}
{{- end }}

{{/* "true" when the gc CronJob is wanted, else empty: gc.enabled, or when that is
unset (null) whether backup.enabled, so a release with backups off still renders. */}}
{{- define "scrap.gcEnabled" -}}
{{- if kindIs "invalid" .Values.gc.enabled -}}
{{- if .Values.backup.enabled }}true{{ end -}}
{{- else if .Values.gc.enabled }}true{{ end -}}
{{- end }}

{{/* Public pages (public.*): the names of its objects in public.namespace, each
at most 63 characters, and its pods' labels. */}}
{{- define "scrap.publicName" -}}
{{- printf "%s-public" (include "scrap.fullname" . | trunc 56 | trimSuffix "-") }}
{{- end }}

{{- define "scrap.receiverName" -}}
{{- printf "%s-receiver" (include "scrap.fullname" . | trunc 54 | trimSuffix "-") }}
{{- end }}

{{- define "scrap.publicSelectorLabels" -}}
app.kubernetes.io/name: {{ printf "%s-public" (include "scrap.name" . | trunc 56 | trimSuffix "-") }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "scrap.publicLabels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{ include "scrap.publicSelectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "scrap.publicImage" -}}
{{ .Values.public.image.repository }}:{{ .Values.public.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/* The receiver's URL as scrap reaches it (SCRAP_PUBLISH_TO). */}}
{{- define "scrap.publishTo" -}}
{{- printf "http://%s.%s.svc:8081" (include "scrap.receiverName" .) .Values.public.namespace }}
{{- end }}

{{/* Fails unless public.enabled has what it needs; empty otherwise. */}}
{{- define "scrap.publicChecks" -}}
{{- if .Values.public.enabled }}
{{- if not .Values.public.tokenSecret.name }}
{{- fail "public.enabled needs public.tokenSecret.name: a Secret (in both namespaces) holding the upload token" }}
{{- end }}
{{- if not .Values.public.site }}
{{- fail "public.enabled needs public.site: the site's public base URL, e.g. https://pages.example.org" }}
{{- end }}
{{- if and .Values.public.createNamespace (eq .Values.public.namespace .Release.Namespace) }}
{{- fail "public.createNamespace with public.namespace the release namespace: that namespace exists already" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "scrap.publicContainerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
runAsNonRoot: true
capabilities:
  drop:
    - ALL
{{- end }}

{{/* authProxy (oauth2-proxy behind ingress-nginx): the ExternalName Service for
/oauth2 and the open Ingress, each at most 63 characters. */}}
{{- define "scrap.oauth2Name" -}}
{{- printf "%s-oauth2" (include "scrap.fullname" . | trunc 56 | trimSuffix "-") }}
{{- end }}

{{- define "scrap.openIngressName" -}}
{{- printf "%s-open" (include "scrap.fullname" . | trunc 58 | trimSuffix "-") }}
{{- end }}

{{/* Fails unless authProxy.enabled has what it needs; empty otherwise. */}}
{{- define "scrap.authProxyChecks" -}}
{{- if .Values.authProxy.enabled }}
{{- if not .Values.ingress.enabled }}
{{- fail "authProxy.enabled needs ingress.enabled: the login is ingress-nginx's auth on scrap's Ingress" }}
{{- end }}
{{- if not .Values.authProxy.service }}
{{- fail "authProxy.enabled needs authProxy.service: oauth2-proxy's in-cluster DNS name, e.g. oauth2-proxy.scrap.svc.cluster.local" }}
{{- end }}
{{- if not .Values.authProxy.allowedEmails }}
{{- fail "authProxy.enabled needs authProxy.allowedEmails: the logins that may use the web app" }}
{{- end }}
{{- if not .Values.mcp.tokenSecret.name }}
{{- fail "authProxy.enabled needs mcp.tokenSecret.name: /mcp is on an Ingress without the login, so it needs the bearer token" }}
{{- end }}
{{- if not .Values.ingress.tls }}
{{- fail "authProxy.enabled needs ingress.tls: the login's cookie is sent over https only" }}
{{- end }}
{{- if not .Values.authProxy.oidc.issuer }}
{{- fail "authProxy.enabled needs authProxy.oidc.issuer: the Keycloak realm whose tokens scrap checks, e.g. https://identity.example.org/realms/dls" }}
{{- end }}
{{- if not .Values.authProxy.oidc.clientId }}
{{- fail "authProxy.enabled needs authProxy.oidc.clientId: the oauth2-proxy's Keycloak client, e.g. scrap" }}
{{- end }}
{{- end }}
{{- end }}

{{/* With authProxy.enabled, scrap checks the proxy's Keycloak token on each request
(ADR 45): the Service is open to any pod in the cluster, so the Ingress's login is
not enough. Only the Deployment serves HTTP, so the CronJobs do without. */}}
{{- define "scrap.oidcEnv" -}}
{{- if .Values.authProxy.enabled }}
- name: SCRAP_OIDC_ISSUER
  value: {{ .Values.authProxy.oidc.issuer | quote }}
- name: SCRAP_OIDC_CLIENT_ID
  value: {{ .Values.authProxy.oidc.clientId | quote }}
- name: SCRAP_ALLOWED_EMAILS
  value: {{ join "," .Values.authProxy.allowedEmails | lower | quote }}
{{- end }}
{{- end }}

{{/* The main Ingress's annotations: ingress.annotations, plus ingress-nginx's auth
annotations (which win) when authProxy.enabled. The auth-url has no allowed_emails
query: some ingress-nginx annotation validation refuses an @ or % in it (DLS's does),
so the owner check is scrap's own token check (scrap.oidcEnv, ADR 45). */}}
{{- define "scrap.ingressAnnotations" -}}
{{- $a := include "scrap.proxyBufferAnnotations" . | fromYaml }}
{{- if .Values.authProxy.enabled }}
{{- $auth := dict
  "nginx.ingress.kubernetes.io/auth-url" (printf "http://%s:%v/oauth2/auth" .Values.authProxy.service .Values.authProxy.port)
  "nginx.ingress.kubernetes.io/auth-signin" "https://$host/oauth2/start?rd=$escaped_request_uri"
  "nginx.ingress.kubernetes.io/auth-response-headers" "X-Auth-Request-Email,X-Auth-Request-Access-Token" }}
{{- $a = merge $auth $a }}
{{- end }}
{{- with $a }}
{{- toYaml . }}
{{- end }}
{{- end }}

{{/* ingress.annotations, with a 16k proxy-buffer-size when authProxy.enabled and it
is not set: the Keycloak login's cookies overflow nginx's 4k default. */}}
{{- define "scrap.proxyBufferAnnotations" -}}
{{- $a := deepCopy (.Values.ingress.annotations | default dict) }}
{{- if .Values.authProxy.enabled }}
{{- $a = merge $a (dict "nginx.ingress.kubernetes.io/proxy-buffer-size" "16k") }}
{{- end }}
{{- toYaml $a }}
{{- end }}
