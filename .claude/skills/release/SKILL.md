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
- Do not wait for main's CI on the merge commit: the tag's CI runs the same
  checks and is the gate (step 3). Only check that the latest finished **CI**
  and **Chart** runs on main did not fail
  (`gh run list -R gilesknap/scrap --branch main --limit 5`).
- Note migrations since the last tag:
  `git diff --name-only <last-tag>..HEAD -- src/scrap/migrations`.
  Script `NNNN_*.sql` sets `user_version` N.

## 2. Pick the version

- Minor for features or a migration; patch for fixes only. No `v` prefix.
- Confirm it with the user unless they named one.

## 3. Tag

- Tag main's HEAD and push the tag over HTTPS, straight after the last merge.
- Then run steps 4 and 5 while the tag's CI runs; merge (step 6) only once
  it has published.
- A deploy needs only two jobs, not the whole run:
  - **CI** `container-publish / manifest` publishes the image to
    `ghcr.io/gilesknap/scrap:<tag>` and `:latest`. It runs only after lint, the
    tests, web and the deploy-script checks pass, so it is the tests' gate too.
  - **Chart** `publish chart` publishes the chart to
    `oci://ghcr.io/gilesknap/charts/scrap` at version `<tag>`.
  - **CI** `container-public-publish / manifest` publishes the public site's
    image, `ghcr.io/gilesknap/scrap-public:<tag>`, behind the same gates. Watch
    it too when the cluster runs public pages (`public.enabled`). The first
    release that publishes it creates the package private: make
    `scrap-public` public in its GitHub package settings, or the cluster
    cannot pull it.
- Watch those two with `gh run view <run-id> -R gilesknap/scrap --json jobs`.
  Docs and the GitHub Release (`release / artifacts`) finish later; check
  them at the end (step 7), but don't hold the deploy for them.
- If a check fails on the tag, nothing is deployed. Stop and tell the user:
  fix it on main and release a new patch version. Don't move the tag, because
  its chart version may already be published.

## 4. Back up

- Start it straight after tagging; it runs while the tag's CI does.
- `kubectl -n scrap create job --from=cronjob/scrap-backup scrap-backup-pre-<x-y-z>`
  (the version with dots as dashes).
- Wait for it to complete; note the backup directory from its logs.
- Skip it only for a UX-only release (CSS, copy, frontend tweaks) with no
  backend, schema or data change.

## 5. Deploy PR

- Open it while the tag's CI runs, so its checks run alongside.
- Clone gilesknap/tpi-k3s-ansible over HTTPS into a temp directory, on a new
  branch.
- In `kubernetes-services/templates/scrap.yaml`, change ONLY the scrap chart's
  `targetRevision` to the new version.
- Commit with the author from the scrap clone's git config (`user.name`,
  `user.email`), and a message ending with the session's attribution line.
- Open a PR titled `scrap <ver>`: the user-visible changes, the backup
  directory (or why it was skipped) and any migration. End the body with the
  session's attribution lines.
- For 1.0 (and its release notes): say that a store or backup below schema 18
  needs 0.16.x first, then 1.0 (the "Upgrading to 1.0 from before 0.16" notes in
  `docs/how-to/deploy-kubernetes.md` and `deploy-single-server.md`). Check the
  live `user_version` is 18 before deploying 1.0, or 1.0 refuses to start.

## 6. Merge

- Merge when all of these hold:
  - the image and chart jobs from step 3 have passed;
  - the backup has completed (or was skipped);
  - the deploy PR's real checks pass: docs, pre-commit, shellcheck.
    CodeRabbit is advisory: never wait on it.
- Squash-merge and delete the branch.
- Merging to main deploys through ArgoCD: a `Recreate` rollout, with a short
  outage.
- ArgoCD only polls git every few minutes, so refresh straight after the
  merge. The `scrap` Application's `targetRevision` is rendered by the parent
  app `all-cluster-services` from tpi-k3s-ansible's main, so refresh that one;
  refreshing `scrap` alone re-reads the old version:
  ```
  kubectl -n argo-cd annotate application all-cluster-services argocd.argoproj.io/refresh=hard --overwrite
  ```
  Within a minute, `kubectl -n argo-cd get application scrap -o jsonpath='{.spec.source.targetRevision}'`
  shows the new version and the rollout starts. If the pod has not been
  replaced a minute after that, refresh `scrap` the same way.

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
- The tag's whole **CI** run has finished green, including docs and
  `release / artifacts`.
- Tell the user in a few lines: version, backup, migration, and what to try
  on the phone.

## 8. Clean up

- Remove the temp tpi-k3s-ansible clone and any other temp clones.
- Fast-forward the main clone.
