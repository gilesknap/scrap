---
name: release
description: "Release scrap and deploy it to the owner's cluster: tag, wait for the image and chart, back up, bump targetRevision in tpi-k3s-ansible, merge when green, verify. Use when asked to release, tag, ship or deploy scrap."
---

# Release

You orchestrate; subagents do the work. How a tag publishes is in
`.github/CONTRIBUTING.md` ("Making a release"); the chart is described in
`docs/how-to/deploy-kubernetes.md`.

## 0. Ground rules

- Run every step in a background subagent, including the waits on CI,
  backups and the rollout. Never block the main thread.
- Every git command against GitHub (fetch, push, clone) uses HTTPS with gh's
  credential helper and `GIT_CONFIG_GLOBAL=/dev/null`, never SSH:
  ```
  GIT_CONFIG_GLOBAL=/dev/null git -c credential.helper='!gh auth git-credential' \
    push https://github.com/gilesknap/scrap.git <ref>
  ```
- The kubectl context `default` is the real cluster; scrap runs in namespace
  `scrap`.
- Get the pod name first, in its own command:
  `kubectl -n scrap get pods -l app.kubernetes.io/name=scrap -o name`.
  Every exec then starts exactly with `kubectl -n scrap exec <pod-name> --`.

## 1. Check main

- Fast-forward the main clone to `origin/main`.
- The **CI** and **Chart** runs on main's HEAD are green
  (`gh run list -R gilesknap/scrap --branch main --limit 5`).
- Note migrations since the last tag:
  `git diff --name-only <last-tag>..HEAD -- src/scrap/migrations`.
  Script `NNNN_*.sql` sets `user_version` N.

## 2. Pick the version

- Minor for features or a migration; patch for fixes only. No `v` prefix.
- Confirm it with the user unless they named one.

## 3. Tag

- Tag main's HEAD and push the tag over HTTPS.
- Wait for the tag's **CI** and **Chart** runs to succeed. They publish the
  image to `ghcr.io/gilesknap/scrap:<tag>` and `:latest`, and the chart to
  `oci://ghcr.io/gilesknap/charts/scrap` at version `<tag>`. The release job
  does not wait for the container job, so check that the image job passed.

## 4. Back up

- `kubectl -n scrap create job --from=cronjob/scrap-backup scrap-backup-pre-<x-y-z>`
  (the version with dots as dashes).
- Wait for it to complete; note the backup directory from its logs.
- Skip it only for a UX-only release (CSS, copy, frontend tweaks) with no
  backend, schema or data change.

## 5. Deploy PR

- Clone gilesknap/tpi-k3s-ansible over HTTPS into a temp directory, on a new
  branch.
- In `kubernetes-services/templates/scrap.yaml`, change ONLY the scrap chart's
  `targetRevision` to the new version.
- Commit with the author from the scrap clone's git config (`user.name`,
  `user.email`), and a message ending with the session's attribution line.
- Open a PR titled `scrap <ver>`: the user-visible changes, the backup
  directory (or why it was skipped) and any migration. End the body with the
  session's attribution lines.

## 6. Merge

- Merge when the real checks pass: docs, pre-commit, shellcheck. CodeRabbit
  is advisory: never wait on it.
- Squash-merge and delete the branch.
- Merging to main deploys through ArgoCD: a `Recreate` rollout, with a short
  outage.

## 7. Verify

- The pod runs the new image, is Ready, with 0 restarts
  (`kubectl -n scrap get pod <pod-name> -o wide` and its
  `.spec.containers[0].image`).
- `pragma user_version`, read-only, matches the expected migration:
  ```
  kubectl -n scrap exec <pod-name> -- python -c "import sqlite3; print(sqlite3.connect('file:/data/scrap.db?mode=ro', uri=True).execute('pragma user_version').fetchone()[0])"
  ```
- `/api/health` responds (port-forward `svc/scrap`, or the exec above with
  `urllib`).
- Check anything specific to this release.
- Tell the user in a few lines: version, backup, migration, and what to try
  on the phone.

## 8. Clean up

- Remove the temp tpi-k3s-ansible clone and any other temp clones.
- Fast-forward the main clone.
