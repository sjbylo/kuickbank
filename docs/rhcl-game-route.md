# RHCL External Service Route: game.demo.bylo.de

This document describes the RHCL (Red Hat Connectivity Link) configuration
that routes traffic from `https://game.demo.bylo.de` through an Istio
gateway on `sno1-ext` to an external VM on the lab network.

Two backend configurations are covered:
- **Option A:** Backend serves plain HTTP (simpler, fewer resources)
- **Option B:** Backend serves HTTPS (requires Istio TLS origination)

## Architecture

### Option A: Plain HTTP backend

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

### Option B: HTTPS backend

```
Browser                 RHCL Gateway (sno1-ext)              Game VM (lab)
  |                     192.168.2.203                        192.168.2.36
  |                          |                                   |
  |--- HTTPS (443) --------->|                                   |
  |   game.demo.bylo.de      |--- HTTPS (9443) ---------------->|
  |   TLS terminated         |   TLS originated by Envoy        |
  |                          |   SNI: game.bylo.de              |
  |<--- response ------------|<--- response --------------------|
```

## VM Details

The game VM (`192.168.2.36`) runs "Der Tippmeister" (FIFA World Cup 2026
tipping game). It can listen on:

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

### 2. DNSPolicy

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

### 3. TLSPolicy

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

---

## Option A: Plain HTTP backend (port 8080)

Only 2 additional resources needed. This is the simplest configuration.

### HTTPRoute

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: game
  namespace: kuickbank
spec:
  parentRefs:
  - name: game-gateway
  hostnames:
  - game.demo.bylo.de
  rules:
  - backendRefs:
    - name: game-external
      port: 8080                      # VM's HTTP port
```

### Headless Service + EndpointSlice

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
    kubernetes.io/service-name: game-external
addressType: IPv4
endpoints:
- addresses:
  - "192.168.2.36"                    # VM's lab network IP
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
  name: game
  namespace: kuickbank
spec:
  parentRefs:
  - name: game-gateway
  hostnames:
  - game.demo.bylo.de
  rules:
  - backendRefs:
    - name: game-external
      port: 9443                      # VM's HTTPS port
```

### Headless Service + EndpointSlice

```yaml
apiVersion: v1
kind: Service
metadata:
  name: game-external
  namespace: kuickbank
spec:
  clusterIP: None
  ports:
  - port: 9443
    targetPort: 9443
    protocol: TCP
    appProtocol: https                # Tells Istio the backend speaks HTTPS
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: game-external-1
  namespace: kuickbank
  labels:
    kubernetes.io/service-name: game-external
addressType: IPv4
endpoints:
- addresses:
  - "192.168.2.36"                    # VM's lab network IP
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
  name: game-external-tls
  namespace: kuickbank
spec:
  host: game-external.kuickbank.svc.cluster.local   # Matches the k8s Service FQDN
  trafficPolicy:
    tls:
      mode: SIMPLE                    # Originate TLS (no client cert / no mTLS)
      sni: game.bylo.de              # SNI the backend's TLS cert expects
    portLevelSettings:
    - port:
        number: 9443
      tls:
        mode: SIMPLE
        sni: game.bylo.de
```

> **Key values:**
> - `mode: SIMPLE` — standard TLS without mutual authentication
> - `sni: game.bylo.de` — the Server Name Indication sent during the TLS
>   handshake; must match the backend's certificate CN/SAN

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
curl -sk --resolve game.demo.bylo.de:443:192.168.2.203 https://game.demo.bylo.de/

# Via CoreDNS (if DNS delegation is configured)
curl -sk https://game.demo.bylo.de/
```

From a browser, add to `/etc/hosts`:

```
192.168.2.203  game.demo.bylo.de
```

Then visit `https://game.demo.bylo.de` (accept the self-signed cert warning).
