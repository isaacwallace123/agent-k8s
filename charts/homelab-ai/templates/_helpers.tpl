{{/*
=============================================================================
_helpers.tpl — homelab-ai Helm chart helper templates
=============================================================================
*/}}

{{/*
Expand the name of the chart.
*/}}
{{- define "homelab-ai.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "homelab-ai.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Selector labels for a given component.
Usage: include "homelab-ai.selectorLabels" (dict "component" "llm" "context" .)
*/}}
{{- define "homelab-ai.selectorLabels" -}}
app.kubernetes.io/name: {{ .context.Chart.Name }}
app.kubernetes.io/component: {{ .component }}
app.kubernetes.io/instance: {{ .context.Release.Name }}
{{- end }}

{{/*
Resolve the storage class for a component.
Uses the component's storageClass if set, otherwise falls back to global.storageClass.
Usage: include "homelab-ai.storageClass" (dict "component" .Values.llm "context" .)
*/}}
{{- define "homelab-ai.storageClass" -}}
{{- if .component.storage.storageClass -}}
{{ .component.storage.storageClass }}
{{- else -}}
{{ .context.Values.global.storageClass }}
{{- end }}
{{- end }}

{{/*
Build a nodeSelector that pins the workload to the pve1 AI node.
Requires both proxmox-host=pve1 AND role=ai so workloads never land
on the control plane (which also carries proxmox-host=pve1).
Node: k3s-worker-node-1
Usage: include "homelab-ai.nodeSelectorPve1" .
*/}}
{{- define "homelab-ai.nodeSelectorPve1" -}}
{{ .Values.global.nodeLabelKey }}: {{ .Values.global.pve1 }}
role: ai
{{- end }}

{{/*
Build a nodeSelector that pins the workload to the pve2 AI node.
Requires both proxmox-host=pve2 AND role=ai so workloads never land
on k3s-worker-node-2 (apps node, role=apps).
Node: k3s-worker-node-3
Usage: include "homelab-ai.nodeSelectorPve2" .
*/}}
{{- define "homelab-ai.nodeSelectorPve2" -}}
{{ .Values.global.nodeLabelKey }}: {{ .Values.global.pve2 }}
role: ai
{{- end }}

{{/*
Render a list of env vars from a component's .env list.
Usage: include "homelab-ai.envList" .Values.llm.env
*/}}
{{- define "homelab-ai.envList" -}}
{{- range . }}
- name: {{ .name }}
  value: {{ .value | quote }}
{{- end }}
{{- end }}
