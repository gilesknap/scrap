# scrap Helm chart

Runs [scrap](https://github.com/gilesknap/scrap) on Kubernetes: one Deployment with exactly
**one replica** and the `Recreate` strategy (scrap's SQLite database has a single writer), a
PersistentVolumeClaim for `/data`, a ClusterIP Service, and a nightly backup CronJob; an Ingress
and a NetworkPolicy are optional.

scrap v0 has **no login**: expose it only on a private network such as your tailnet, or behind an
authenticating proxy.

```
helm install scrap ./charts/scrap --namespace scrap --create-namespace -f my-values.yaml
```

Values are described in [values.yaml](values.yaml). The full guide (secrets, exposure with the
Tailscale operator, upgrades, backup and restore, Argo CD) is
[Deploy on Kubernetes](https://gilesknap.github.io/scrap/main/how-to/deploy-kubernetes.html).

Checks: `./charts/test-chart.sh` (needs `helm` and `kubeconform`).
