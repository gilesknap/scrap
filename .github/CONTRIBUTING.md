# Contribute to the project

Contributions and issues are most welcome! All issues and pull requests are
handled through [GitHub](https://github.com/gilesknap/scrap/issues). Also, please check for any existing issues before
filing a new one. If you have a great idea but it involves big changes, please
file a ticket before making a pull request! We want to make sure you don't spend
your time coding something that might not fit the scope of the project.

To judge the scope, read the
[Goals](https://gilesknap.github.io/scrap/main/#goals) in the README
(tiny, one service, no login code, not multi-user) and the
[design](https://github.com/gilesknap/scrap/blob/main/docs/explanations/design.md). For a UI change see the
[design system](https://github.com/gilesknap/scrap/blob/main/docs/explanations/design-system.md). Record a
significant decision as an ADR: copy
[`docs/explanations/decisions/COPYME`](https://github.com/gilesknap/scrap/blob/main/docs/explanations/decisions/COPYME)
to the next number (see
[ADR 1](https://github.com/gilesknap/scrap/blob/main/docs/explanations/decisions/0001-record-architecture-decisions.md)).

## Issues

Use the bug report or issue template. Both ask for Acceptance Criteria, the
specific conditions that say the issue is fixed. Open-ended ideas and design
questions go in an issue too (the issue template covers design discussions).

## Set up and check

You need [uv](https://docs.astral.sh/uv/). `uv sync` installs the project and its
dev dependencies (the `dev` group) into a virtual environment. Python 3.11 or
newer is supported, CI covers 3.11 to 3.14, and `.python-version` pins 3.11 for
local work.

```sh
uv sync
uv run pre-commit install    # run the hooks on every commit
uv run tox -p                # pre-commit, type-checking, tests and docs in parallel
```

or one at a time:

```sh
uv run tox -e pre-commit       # ruff lint and format, uv.lock sync, gitleaks, file checks
uv run tox -e type-checking    # pyright on src and tests
uv run tox -e tests            # pytest with coverage
uv run tox -e docs             # build the docs into build/html
uv run tox -e docs-autobuild   # rebuild the docs on change
```

The docs build fails on any warning and needs
[graphviz](https://graphviz.org/) installed. pytest also runs the doctests in
`docs/` and `src/`, and treats warnings as errors.

### Writing the docs

The docs are MyST Markdown under `docs/`, in the Diataxis folders `tutorials/`,
`how-to/`, `explanations/` and `reference/`. A new file in `tutorials/`,
`how-to/` or `explanations/` is picked up by the glob in that section's
toctree. `docs/reference.md` lists its pages one by one, so add a line there
for a new reference page.

- Use relative links and `{ref}` labels inside `docs/`. In `README.md` and
  this file use absolute GitHub URLs, because `docs/how-to/contribute.md` only
  includes this file and a relative link would resolve from there.
- The build fails on any warning. `conf.py` sets `nitpicky`, so a reference
  that does not resolve is a warning too.
- The build needs network access (it fetches the version switcher and the
  Python intersphinx inventory) and a git checkout (a development version takes
  its name from `git branch --show-current`).
- `docs-autobuild` and `scrap serve` both default to port 8000. Pass another
  port to one of them, for example
  `uv run tox -e docs-autobuild -- --port 8001`.
- A weekly workflow (Wednesdays, also runnable by hand from the Actions tab)
  checks that the links in the docs still resolve. To run the same check
  locally: `uv run tox -e docs -- -b linkcheck`.

## Run it from a checkout

```sh
uv run scrap serve --data-dir ./data    # port 8000 by default
curl http://127.0.0.1:8000/healthz
```

`uv run scrap --help` lists the other commands. The UI is the PWA built from
`web/`, so build it first (next section); without it `scrap serve` still serves
the API. See the
[API reference](https://github.com/gilesknap/scrap/blob/main/docs/reference/api.md) and
[capture from your phone](https://github.com/gilesknap/scrap/blob/main/docs/how-to/use-the-pwa.md).

Capture and search work without Claude. The Claude features (photo ingest and
page enrichment) need `SCRAP_INGEST=on` and `ANTHROPIC_API_KEY` in the
environment. The tests do not call Claude.

## Working on the PWA

The PWA is TypeScript in `web/`, built with Node 22 into `src/scrap/static/`.
The devcontainer does not install Node, so install it yourself for this work.

```sh
npm --prefix web ci
npm --prefix web run build   # writes src/scrap/static/, which scrap serve picks up
npm --prefix web run dev     # Vite dev server; run scrap serve beside it, it proxies to port 8000
npm --prefix web run check   # Biome and tsc
npm --prefix web run fix     # Biome, applying fixes
npm --prefix web test        # vitest unit tests
npm --prefix web run size    # after a build: the app shell stays within 16 kB gzipped
npm --prefix web run e2e     # Playwright against a real scrap serve
```

Playwright needs a browser first: `npx playwright install chromium` (from `web/`).
The e2e tests serve on port 8791 with a throwaway data folder; set
`SCRAP_E2E_PORT` or `SCRAP_E2E_DATA` to change either.
The specs share one server and one data folder, so they run on one worker. CI splits them across
six runners (`--shard=N/6`), each with its own server and data. To go faster locally, run shards
side by side, each on its own port: `SCRAP_E2E_PORT=8801 npm run e2e -- --shard=1/4`, and so on.

## Tests and coverage

New behaviour needs a test: pytest under `tests/` (`conftest.py` provides the
`client` and `note` fixtures), vitest under `web/tests/` and Playwright under
`web/e2e/`.

`uv run tox -e tests` prints a coverage report and writes `cov.xml`. CI uploads
it to Codecov, which reports on the pull request. Nothing fails the build on a
coverage drop, so please make sure coverage remains the same or is improved by a
pull request.

## Deployment scripts and the Helm chart

The scripts in `deploy/` are covered by `tests/test_deploy.py`, which runs under
pytest. Its tests put a fake `podman` (or `systemctl`) in a temporary folder that records its
arguments (the scripts call `/usr/bin/podman`, so the tests point `PODMAN` at the
fake; it is a test hook, not a setting), so none of them needs podman or root. When you change a script, add
a test of that kind instead of trying it on a live install.

`./deploy/test-retention.sh` runs the `scrap-backup` pruning checks on their
own, also without podman or root, and prints `ok` or `FAIL` for each case. It
checks that only the newest N backups are kept, that paths with spaces are safe,
that symlinks and other directories are left alone, that a bad `KEEP` value
(`0`, `00`, empty, `abc`, `-1`, `2x`) is refused, and that a second run in the
same second stops before it calls podman. `tests/test_deploy.py` runs it as
`test_backup_retention`, and also tests the `scrap-gc` wrapper. Extend these
when you change `scrap-backup` or `scrap-gc`. `./deploy/test-check-env.sh` does the
same for `deploy/check-env`, which `install.sh` and `smoke.sh` use to refuse env
files that systemd and the shell would read differently.

After a change to `charts/`, run `./charts/test-chart.sh` (needs `helm` and
`kubeconform` on your PATH). For every `charts/scrap/ci/*-values.yaml` it:

- lints with `--strict`, renders the chart (the `long-names` case uses a
  53-character release name) and validates the output with `kubeconform
  -strict` against Kubernetes 1.30.0 and 1.36.5. Set `K8S_VERSIONS` to change
  that, for example `K8S_VERSIONS="1.30.0" ./charts/test-chart.sh`.
- fails if a Secret or ConfigMap is rendered, if `ANTHROPIC_API_KEY` or
  `SCRAP_NOTIFY_URL` appears as a plain value, if the Deployment is not one
  replica with `Recreate`, or if a name or label exceeds the Kubernetes limits.

It also checks that the chart refuses values such as `ingest.enabled` without
`existingSecret`, `ingest.apiKey`, an unknown top-level key, `backup.keep` of
`0` or `-1`, and a non-numeric or negative budget. Finally, every `SCRAP_*` or
`ANTHROPIC_*` variable the chart sets must have a row in the Settings table in
`docs/reference/api.md` (a line starting ``| `VAR` |``) or be read by
`deploy/scrap-backup`, so document a new variable there.

To add a chart option, update `values.yaml` and `values.schema.json` (which
refuses unknown keys) and add a `ci/<name>-values.yaml` that sets it. A release
tag sets the chart's `version` and `appVersion` when CI publishes it, so
`charts/scrap/Chart.yaml` keeps the placeholder `0.0.0`. CI runs the script
under Helm 3 and Helm 4.

## Pull requests

Fill in the pull request template:

- Start with `Fixes #ISSUE`, linking the issue.
- Give the reviewer steps to test it.
- Write a title that would make sense to a user in a list of release notes.

CI must pass:

- **lint**: the pre-commit hooks (ruff lint and format, `uv.lock` in sync,
  gitleaks, file checks) and pyright.
- **test**: pytest on Python 3.11, 3.12, 3.13 and 3.14.
- **web**: Biome and tsc, vitest, the PWA build and size budget, and Playwright.
- **container**, **docs** and **dist**: the container image, the docs and the
  package must all build. The image is published on release tags.
- **Chart**: `charts/test-chart.sh` under Helm 3 and Helm 4.

## Making a release

Releases are cut by pushing a tag. The tag is the version, with no `v` prefix
(for example `0.2.0`), and the package version is taken from it by
`setuptools_scm`, so there is no version to edit in `pyproject.toml`
(`src/scrap/_version.py` is generated).

1. On `main`, with CI green, tag the merge commit and push the tag (the tag,
   not a branch, starts the release). The chart version needs no edit: CI sets
   it from the tag.

   ```sh
   git tag X.Y.Z
   git push origin X.Y.Z
   ```

The CI workflow then runs on the tag. The GitHub Release is created once the
`dist`, `test`, `docs` and `web` jobs have passed. It has generated release
notes with the sdist, the wheel and `docs.zip` attached. In parallel:

- The multi-arch image (amd64 and arm64) is pushed to
  `ghcr.io/gilesknap/scrap` as `X.Y.Z` and `latest`, provided the `test` job
  passed.
- The docs are published to GitHub Pages as a new version in the version
  switcher.

Things to know:

- A tag containing `a`, `b` or `rc` (such as `0.2.0rc1`) is marked as a
  pre-release on GitHub, but the image is still also tagged `latest`.
- The **Chart** workflow is separate. On a tag it packages the chart with
  `version` and `appVersion` taken from the tag and pushes it to
  `oci://ghcr.io/gilesknap/charts/scrap`. A pre-release tag `X.Y.ZrcN` (or `aN`,
  `bN`) is published as chart version `X.Y.Z-rc.N`, with `appVersion` the tag as
  written so the image resolves. A tag in any other form fails the publish
  only; the image and the release are still published. The first time, make the
  `charts/scrap` package public in the GitHub package settings.
- The release job does not wait for the `container` job, so check that the
  image was pushed.
- Nothing is published to PyPI.

## Developer Information

It is recommended that developers use a [vscode devcontainer](https://code.visualstudio.com/docs/devcontainers/containers),
with podman or docker. The configuration in `.devcontainer/` builds the `developer`
stage of the `Dockerfile` (Ubuntu with graphviz), then runs `uv sync` and installs the
pre-commit hooks. It does not include Node.

The container mounts the parent directory of your checkout at `/workspaces`. It
runs with `--net=host`, so `scrap serve` on port 8000 inside the container is
`localhost:8000` on the host, and clashes with anything already using that port
(pass `--port` to `scrap serve` to avoid it). The virtual environment is not
`.venv`: it lives in the `devcontainer-shared-cache` volume (mounted at
`/cache`, along with the uv and pre-commit caches) under a name taken from the
workspace path. It is already on `PATH` and set as the VS Code interpreter, so
`uv run` works as normal. To start clean, remove that volume.

Renovate keeps `uv.lock` current and automerges its lock-file maintenance pull
requests once CI passes. It is told to leave the workflow action versions and
the Ubuntu and devcontainer base images alone, because the Copier template
manages them (`copier update`), so do not expect update pull requests for those.
After you change dependencies in `pyproject.toml`, run `uv sync` and commit
`uv.lock`; the pre-commit `uv-sync` hook checks it.

This project was created using the [Diamond Light Source Copier Template](https://github.com/DiamondLightSource/python-copier-template) for Python projects
([ADR 2](https://github.com/gilesknap/scrap/blob/main/docs/explanations/decisions/0002-switched-to-python-copier-template.md)).
For generic tasks the template's
[How-to guides](https://diamondlightsource.github.io/python-copier-template/5.4.0/how-to.html)
may help, but the commands above are the ones this project uses. Update that link when
`copier update` moves the template version (`_commit` in `.copier-answers.yml`).
