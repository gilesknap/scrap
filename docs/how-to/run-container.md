# Run in a container

Pre-built containers with scrap and its dependencies already
installed are available on [Github Container Registry](https://ghcr.io/gilesknap/scrap).

## Starting the container

To pull the container from github container registry and run:

```
$ docker run ghcr.io/gilesknap/scrap:latest --version
```

To get a released version, use a numbered release instead of `latest`.

To run scrap as a service on one machine, see [](deploy-single-server.md); on Kubernetes,
see [](deploy-kubernetes.md).
