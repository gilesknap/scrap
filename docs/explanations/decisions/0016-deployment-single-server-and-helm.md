# 16. Deployment: rootless podman units for one server, a Helm chart for Kubernetes

Date: 2026-10-19 (#5, #24)

## Status

Accepted

## Context

The goal was a home k3s cluster, but a canary on a single VPS was needed first, and other people
should be able to run scrap with either. The design assumes exactly one writer and a loopback-only
listener.

## Decision

- One multi-arch (arm64, amd64) container image runs everything; CI builds it and the chart.
- **Single server:** `deploy/install.sh` installs rootless podman systemd user units for a dedicated
  user: the service, a gated backup timer with safe retention (only run-named directories are ever
  deleted), and a gc timer. The container publishes only to `127.0.0.1`; Tailscale Serve fronts it.
  Docker works but is not the primary path. Updates restart onto a new image and pass ingest
  settings through.
- **Kubernetes:** a Helm chart with exactly one replica and strategy `Recreate`, a restricted Pod
  Security profile (uid 10001, read-only root, no capabilities), no service-account token, a PVC kept
  on uninstall, a nightly backup CronJob, and an optional NetworkPolicy and Ingress. The Tailscale
  operator is the recommended exposure. Argo CD notes are included.
- Restore is a CLI command that works from a read-only backup.

## Consequences

- No autoscaling or HA (see [](0003-one-process-sqlite-and-a-folder.md)).
- Both paths document that v0 has no login and that local or in-cluster workloads can reach it.
