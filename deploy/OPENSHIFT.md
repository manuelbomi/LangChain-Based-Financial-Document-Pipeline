# Running on OpenShift

The manifests under `deploy/k8s/` are plain Kubernetes and work on
OpenShift with a couple of adjustments, since OpenShift's default Security
Context Constraints (SCCs) are stricter than a vanilla cluster's:

1. **Don't hardcode a UID.** OpenShift's default `restricted` SCC assigns
   each namespace a UID range and rejects pods that request a specific
   `runAsUser` outside it. Remove the `runAsUser: 10001` line from
   `cronjob.yaml` / `job-initial-ingest.yaml` (or set it to a UID your
   cluster's SCC actually allows) and let OpenShift assign one -- the
   Docker image already runs as the unprivileged `appuser` by default, so
   omitting `runAsUser` still avoids root.

2. **`fsGroup` is usually fine** under the `restricted` SCC, but if your
   cluster enforces a specific supplemental-group range, drop `fsGroup` too
   and let it default.

3. **Route/Service**: this toolkit is a batch CLI, not an HTTP service, so
   no `Route` is needed. If you wrap it with an HTTP trigger later (see
   README "Roadmap"), add a standard OpenShift `Route` in front of the
   `/healthz` and `/readyz` endpoints at that point.

4. **Image import**: push the built image to your OpenShift-visible
   registry (internal registry or ImageStream) and reference it by its
   internal pull spec (e.g.
   `image-registry.openshift-image-registry.svc:5000/<namespace>/langchain-document-pipeline-toolkit:latest`)
   instead of `langchain-document-pipeline-toolkit:latest` in the manifests.

5. **PVC storage class**: `persistent-volume-claim.yaml` doesn't set
   `storageClassName`, so it uses your cluster's default. Set one
   explicitly if your OpenShift cluster requires it.

Everything else (ConfigMap, CronJob schedule, resource requests/limits,
`drop: ["ALL"]` capabilities) applies unchanged.
