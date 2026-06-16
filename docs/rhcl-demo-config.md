# RHCL Multi-Cluster Demo Configuration

## Architecture

- **sno1-ext** (192.168.2.202) — Primary DNS controller, runs CoreDNS
- **sno2-ext** (192.168.2.205) — Delegate (secondary)
- **Bastion** (192.168.2.38) — Shared PostgreSQL DB, container image registry
- **Domain**: `kuickbank.demo.bylo.de`
- **CoreDNS**: `192.168.2.201` (in `kuadrant-coredns` namespace on sno1-ext)

---

## sno1-ext (Primary)

### Gateway

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: kuickbank-gateway
  namespace: kuickbank
spec:
  gatewayClassName: istio
  listeners:
  - name: kuickbank
    hostname: kuickbank.demo.bylo.de
    port: 443
    protocol: HTTPS
    tls:
      mode: Terminate
      certificateRefs:
      - name: kuickbank-gateway-tls
    allowedRoutes:
      namespaces:
        from: Same
```

### HTTPRoute

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: kuickbank
  namespace: kuickbank
spec:
  parentRefs:
  - name: kuickbank-gateway
  hostnames:
  - kuickbank.demo.bylo.de
  rules:
  - backendRefs:
    - name: kuickbank
      port: 8080
```

### DNSPolicy

```yaml
apiVersion: kuadrant.io/v1
kind: DNSPolicy
metadata:
  name: kuickbank-dns
  namespace: kuickbank
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: kuickbank-gateway
  providerRefs:
  - name: coredns-credentials
  healthCheck:
    path: /health
    port: 443
    protocol: HTTPS
    interval: 30s
    failureThreshold: 2
```

> Simple routing (no `loadBalancing`) produces a multi-value A record, enabling automatic health-check failover.

### TLSPolicy

```yaml
apiVersion: kuadrant.io/v1
kind: TLSPolicy
metadata:
  name: kuickbank-tls
  namespace: kuickbank
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: kuickbank-gateway
  issuerRef:
    group: cert-manager.io
    kind: ClusterIssuer
    name: selfsigned-issuer
```

### DNS Provider Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: coredns-credentials
  namespace: kuickbank
type: kuadrant.io/coredns
stringData:
  ZONES: demo.bylo.de
```

### Multi-Cluster Interconnection Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: sno2-ext-cluster
  namespace: openshift-operators
  labels:
    kuadrant.io/multicluster-kubeconfig: "true"
type: Opaque
data:
  kubeconfig: <base64-encoded sno2-ext kubeconfig>
```

---

## sno2-ext (Delegate)

### Gateway

Same as sno1-ext (identical YAML).

### HTTPRoute

Same as sno1-ext (identical YAML).

### DNSPolicy

```yaml
apiVersion: kuadrant.io/v1
kind: DNSPolicy
metadata:
  name: kuickbank-dns
  namespace: kuickbank
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: kuickbank-gateway
  delegate: true
  healthCheck:
    path: /health
    port: 443
    protocol: HTTPS
    interval: 30s
    failureThreshold: 2
```

> Note: `delegate: true` and no `providerRefs` — sno2-ext does not write to CoreDNS directly.

### TLSPolicy

Same as sno1-ext (identical YAML).

### DNS Operator Config

```yaml
# ConfigMap patched on sno2-ext:
apiVersion: v1
kind: ConfigMap
metadata:
  name: dns-operator-controller-env
  namespace: openshift-operators
data:
  DELEGATION_ROLE: secondary
```

---

## App Deployment (both clusters)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kuickbank
  namespace: kuickbank
spec:
  replicas: 1
  selector:
    matchLabels:
      app: kuickbank
  template:
    metadata:
      labels:
        app: kuickbank
    spec:
      containers:
      - name: kuickbank
        image: 192.168.2.38:5000/kuickbank:latest
        ports:
        - containerPort: 8080
        env:
        - name: CLUSTER_NAME
          value: sno1-ext          # or sno2-ext
        - name: APP_COLOR
          value: green             # or blue
        - name: DB_TYPE
          value: postgresql
        - name: ENDPOINT_ADDRESS
          value: "192.168.2.38"
        - name: PORT
          value: "5432"
        - name: DB_NAME
          value: kuickbank
        - name: MASTER_USERNAME
          value: bankuser
        - name: MASTER_PASSWORD
          value: bankpass
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 30
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "500m"
---
apiVersion: v1
kind: Service
metadata:
  name: kuickbank
  namespace: kuickbank
spec:
  selector:
    app: kuickbank
  ports:
  - port: 8080
    targetPort: 8080
```

---

## DNS Record Structure (simple routing)

```
kuickbank.demo.bylo.de    A → 192.168.2.202  (sno1-ext)
kuickbank.demo.bylo.de    A → 192.168.2.205  (sno2-ext)
```

DNS clients receive both IPs (round-robin). When a health check fails,
the unhealthy IP is automatically removed from the A record.

---

## Failover Demo Steps

1. **Show both clusters responding**: `dig @192.168.2.201 kuickbank.demo.bylo.de +short`
2. **Simulate cluster failure**: `oc delete gateway kuickbank-gateway -n kuickbank` (on sno2-ext)
3. **Verify DNS returns only sno1-ext**: `dig @192.168.2.201 kuickbank.demo.bylo.de +short`
4. **Restore**: Re-apply the Gateway YAML on sno2-ext
5. **Verify both IPs return**: DNS shows both within ~30s

---

## Known Limitations

- **DNS TTL**: Top-level CNAMEs have 300s TTL (hardcoded by DNS operator). macOS caches this.
- **Health check failover**: With simple routing, health checks can automatically unpublish unhealthy IPs from the multi-value A record. Failover should work by scaling the app to 0 (no need to delete the Gateway).
- **Browser stickiness**: Browsers reuse HTTPS connections; use incognito or different browsers to see both clusters.
