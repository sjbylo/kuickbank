# RHCL External Service Route: game.demo.bylo.de

This document describes the RHCL (Red Hat Connectivity Link) configuration
that routes traffic from `https://game.demo.bylo.de` through an Istio
gateway on `sno1-ext` to an external VM on the lab network.

## Architecture

```
Browser                 RHCL Gateway (sno1-ext)              Game VM (lab)
  |                     192.168.2.203                        192.168.2.36
  |                          |                                   |
  |--- HTTPS (443) --------->|                                   |
  |   game.demo.bylo.de      |--- HTTP (8080) ----------------->|
  |   TLS terminated         |   plain HTTP to backend          |
  |                          |                                   |
  |<--- response ------------|<--- response --------------------|
```

The gateway terminates the client TLS connection (self-signed cert) and
forwards to the backend VM over plain HTTP. No TLS origination needed.

## VM Details

The game VM (`192.168.2.36`) runs "Der Tippmeister" (FIFA World Cup 2026
tipping game) and listens on:

- **HTTP port 8080** — serves the app directly over plain HTTP

## Resources (all in namespace `kuickbank` on sno1-ext)

### 1. Gateway

Creates an Istio gateway pod with a LoadBalancer IP (`192.168.2.203` via MetalLB).

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: game-gateway
  namespace: kuickbank
spec:
  gatewayClassName: istio            # Uses Istio as the Gateway API provider
  listeners:
  - name: game
    hostname: game.demo.bylo.de      # Only accepts requests for this hostname
    port: 443
    protocol: HTTPS
    tls:
      mode: Terminate                # Gateway terminates client TLS
      certificateRefs:
      - name: game-gateway-tls       # Secret created automatically by TLSPolicy
    allowedRoutes:
      namespaces:
        from: Same
```

### 2. HTTPRoute

Binds to the Gateway and forwards matching requests to the `game-external`
Service on port 8080.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: game
  namespace: kuickbank
spec:
  parentRefs:
  - name: game-gateway               # Attaches to the Gateway above
  hostnames:
  - game.demo.bylo.de
  rules:
  - backendRefs:
    - name: game-external             # Headless Service pointing to the VM
      port: 8080                      # VM's HTTP port
```

### 3. DNSPolicy

Publishes an A record for `game.demo.bylo.de` to CoreDNS and runs a health
check against the gateway to verify the backend is reachable.

```yaml
apiVersion: kuadrant.io/v1
kind: DNSPolicy
metadata:
  name: game-dns
  namespace: kuickbank
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: game-gateway
  providerRefs:
  - name: coredns-credentials         # Secret with CoreDNS zone config
  healthCheck:
    failureThreshold: 3               # Mark unhealthy after 3 consecutive failures
    interval: 60s                     # Probe every 60 seconds
    path: /login                      # Returns 200 (root / returns 302 which fails the probe)
    port: 443
    protocol: HTTPS
```

> **Note:** No `loadBalancing` section because this route only exists on
> `sno1-ext` (single cluster).

### 4. TLSPolicy

Automatically generates a self-signed certificate for the gateway listener
hostname via cert-manager.

```yaml
apiVersion: kuadrant.io/v1
kind: TLSPolicy
metadata:
  name: game-tls
  namespace: kuickbank
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: game-gateway
  issuerRef:
    group: cert-manager.io
    kind: ClusterIssuer
    name: selfsigned-issuer           # Replace with a real CA for production
```

### 5. Headless Service + EndpointSlice

A headless Service (`clusterIP: None`) with a manually managed EndpointSlice
points to the VM's lab IP. This is how Kubernetes routes traffic to an
endpoint outside the cluster.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: game-external
  namespace: kuickbank
spec:
  clusterIP: None                     # Headless — no cluster IP allocated
  ports:
  - port: 8080
    targetPort: 8080
    protocol: TCP
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: game-external-1
  namespace: kuickbank
  labels:
    kubernetes.io/service-name: game-external   # Links this slice to the Service
addressType: IPv4
endpoints:
- addresses:
  - "192.168.2.36"                    # VM's lab network IP
ports:
- port: 8080
  protocol: TCP
```

> **Note:** No `appProtocol: https` or Istio DestinationRule needed since
> the backend serves plain HTTP. This is the simplest possible external
> service configuration.

## Why not ExternalName?

A `Service type: ExternalName` would be simpler (one resource instead of
two), but Istio does not create Envoy upstream clusters for ExternalName
services in Gateway API mode. The headless Service + EndpointSlice approach
is the supported pattern.

## Testing

From the bastion (or any host that can reach `192.168.2.203`):

```bash
# Direct test using gateway IP
curl -sk --resolve game.demo.bylo.de:443:192.168.2.203 https://game.demo.bylo.de/

# Via CoreDNS (if DNS delegation is configured)
curl -sk https://game.demo.bylo.de/
```

From a browser, add to `/etc/hosts`:

```
192.168.2.203  game.demo.bylo.de
```

Then visit `https://game.demo.bylo.de` (accept the self-signed cert warning).
