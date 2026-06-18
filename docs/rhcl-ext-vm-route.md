# RHCL External Service Route: ext-vm.demo.bylo.de

This document describes the RHCL (Red Hat Connectivity Link) configuration
that routes traffic from `https://ext-vm.demo.bylo.de` through an Istio
gateway on `sno1-ext` to an external VM on the lab network.

Two backend configurations are covered:
- **Option A:** Backend serves plain HTTP (simpler, fewer resources)
- **Option B:** Backend serves HTTPS (requires Istio TLS origination)

## Architecture

### Option A: Plain HTTP backend

```
Browser                 RHCL Gateway (sno1-ext)              VM (lab)
  |                     192.168.2.203                        192.168.2.36
  |                          |                                   |
  |--- HTTPS (443) --------->|                                   |
  |   ext-vm.demo.bylo.de    |--- HTTP (8080) ----------------->|
  |   TLS terminated         |   plain HTTP to backend          |
  |                          |                                   |
  |<--- response ------------|<--- response --------------------|
```

### Option B: HTTPS backend

```
Browser                 RHCL Gateway (sno1-ext)              VM (lab)
  |                     192.168.2.203                        192.168.2.36
  |                          |                                   |
  |--- HTTPS (443) --------->|                                   |
  |   ext-vm.demo.bylo.de    |--- HTTPS (9443) ---------------->|
  |   TLS terminated         |   TLS originated by Envoy        |
  |                          |                                   |
  |<--- response ------------|<--- response --------------------|
```

## VM Details

The external VM (`192.168.2.36`) can listen on:

- **HTTP port 8080** — plain HTTP (Option A)
- **HTTPS port 9443** — TLS-encrypted (Option B)

---

## Common Resources (both options)

These 4 resources are identical regardless of backend protocol.

### 1. Gateway

Creates an Istio gateway pod with a LoadBalancer IP (`192.168.2.203` via MetalLB).

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: ext-vm-gateway
  namespace: demo-ext-vm
spec:
  gatewayClassName: istio
  listeners:
  - name: ext-vm
    hostname: ext-vm.demo.bylo.de
    port: 443
    protocol: HTTPS
    tls:
      mode: Terminate
      certificateRefs:
      - name: ext-vm-gateway-tls
    allowedRoutes:
      namespaces:
        from: Same
```

### 2. DNSPolicy

Publishes an A record for `ext-vm.demo.bylo.de` to CoreDNS.

```yaml
apiVersion: kuadrant.io/v1
kind: DNSPolicy
metadata:
  name: ext-vm-dns
  namespace: demo-ext-vm
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: ext-vm-gateway
  providerRefs:
  - name: coredns-credentials
```

> **Note:** No `loadBalancing` section because this route only exists on
> `sno1-ext` (single cluster).

### 3. TLSPolicy

Automatically generates a self-signed certificate for the gateway listener
hostname via cert-manager.

```yaml
apiVersion: kuadrant.io/v1
kind: TLSPolicy
metadata:
  name: ext-vm-tls
  namespace: demo-ext-vm
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: ext-vm-gateway
  issuerRef:
    group: cert-manager.io
    kind: ClusterIssuer
    name: selfsigned-issuer
```

---

## Option A: Plain HTTP backend (port 8080)

Only 2 additional resources needed. This is the simplest configuration.

### HTTPRoute

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: ext-vm
  namespace: demo-ext-vm
spec:
  parentRefs:
  - name: ext-vm-gateway
  hostnames:
  - ext-vm.demo.bylo.de
  rules:
  - backendRefs:
    - name: ext-vm-backend
      port: 8080
```

### Headless Service + EndpointSlice

```yaml
apiVersion: v1
kind: Service
metadata:
  name: ext-vm-backend
  namespace: demo-ext-vm
spec:
  clusterIP: None
  ports:
  - port: 8080
    targetPort: 8080
    protocol: TCP
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: ext-vm-backend-1
  namespace: demo-ext-vm
  labels:
    kubernetes.io/service-name: ext-vm-backend
addressType: IPv4
endpoints:
- addresses:
  - "192.168.2.36"
ports:
- port: 8080
  protocol: TCP
```

**Total: 5 resources** (Gateway, DNSPolicy, TLSPolicy, HTTPRoute, Service+EndpointSlice)

---

## Option B: HTTPS backend (port 9443)

3 additional resources needed. The extra DestinationRule tells Envoy to
originate TLS when connecting to the backend.

### HTTPRoute

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: ext-vm
  namespace: demo-ext-vm
spec:
  parentRefs:
  - name: ext-vm-gateway
  hostnames:
  - ext-vm.demo.bylo.de
  rules:
  - backendRefs:
    - name: ext-vm-backend
      port: 9443
```

### Headless Service + EndpointSlice

```yaml
apiVersion: v1
kind: Service
metadata:
  name: ext-vm-backend
  namespace: demo-ext-vm
spec:
  clusterIP: None
  ports:
  - port: 9443
    targetPort: 9443
    protocol: TCP
    appProtocol: https
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: ext-vm-backend-1
  namespace: demo-ext-vm
  labels:
    kubernetes.io/service-name: ext-vm-backend
addressType: IPv4
endpoints:
- addresses:
  - "192.168.2.36"
ports:
- port: 9443
  protocol: TCP
```

### Istio DestinationRule (only needed for HTTPS backend)

Tells the Envoy proxy in the gateway pod to originate a TLS connection
to the backend.

```yaml
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: ext-vm-backend-tls
  namespace: demo-ext-vm
spec:
  host: ext-vm-backend.demo-ext-vm.svc.cluster.local
  trafficPolicy:
    tls:
      mode: SIMPLE
    portLevelSettings:
    - port:
        number: 9443
      tls:
        mode: SIMPLE
```

**Total: 6 resources** (Gateway, DNSPolicy, TLSPolicy, HTTPRoute, Service+EndpointSlice, DestinationRule)

---

## Why not ExternalName?

A `Service type: ExternalName` would be simpler (one resource instead of
two), but Istio does not create Envoy upstream clusters for ExternalName
services in Gateway API mode. The headless Service + EndpointSlice approach
is the supported pattern.

## Testing

From the bastion (or any host that can reach `192.168.2.203`):

```bash
# Direct test using gateway IP
curl -sk --resolve ext-vm.demo.bylo.de:443:192.168.2.203 https://ext-vm.demo.bylo.de/

# Via CoreDNS (if DNS delegation is configured)
curl -sk https://ext-vm.demo.bylo.de/
```

From a browser, add to `/etc/hosts`:

```
192.168.2.203  ext-vm.demo.bylo.de
```

Then visit `https://ext-vm.demo.bylo.de` (accept the self-signed cert warning).
