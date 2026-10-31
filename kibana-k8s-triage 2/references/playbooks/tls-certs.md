# Playbook — TLS / certificates

Entry: `TLS-*` signatures, `TLS_error` in `upstream_transport_failure_reason`, sudden handshake failures, certificate expiry window.

## 1. Classify the TLS leg

| Leg | Who terminates | Evidence location |
|---|---|---|
| Client → Akamai | Akamai edge cert | Not in Kibana usually; users see browser cert errors |
| Akamai/F5/NGINX → Istio gateway | Gateway `credentialName` secret | Gateway logs: `response_code 0`, `filter_chain_not_found`, SDS errors |
| Gateway → app sidecar (mTLS) | Istio CA (istiod or plugged CA) | Gateway `UF` + `TLS_error` |
| Sidecar → sidecar (mTLS) | Istio CA | Caller outbound `UF` + `TLS_error` |
| App → external HTTPS (app-originated TLS) | Target's public cert, app truststore | App `PKIX`, `SSLHandshakeException` |
| Sidecar-originated TLS (DR `tls.mode: SIMPLE/MUTUAL`) | DR config + target cert | Sidecar outbound `TLS_error` |
| App → Kafka/Cassandra/DB/Redis TLS | Broker/node certs, app truststore/keystore | App client exceptions |
| App → Key Vault / AAD | Microsoft certs | App `PKIX` if corporate proxy re-signs |

## 2. Decode

| Evidence | Root cause | Next |
|---|---|---|
| `PKIX path building failed` | App truststore lacks issuing CA (target rotated to new CA / intermediate; new base image dropped custom cacerts) | Was there a new image (base image change)? Which host (`authority`/message)? |
| `CertificateExpiredException` / `certificate has expired` / `SSLV3_ALERT_CERTIFICATE_EXPIRED` | Expired cert. Alert = *peer* says our client cert expired | Which side? Alert received → ours; exception thrown locally → theirs |
| `No subject alternative names matching` | Hostname/SAN mismatch: calling by IP, new hostname, wildcard depth | Compare host called vs cert SAN (message often prints both) |
| `certificate_unknown` / `bad_certificate` / `UNKNOWN_CA` received | Server rejected our client cert (mTLS to external/Kafka/Apigee) | Client cert rotated? Keystore secret changed (new RS)? |
| `WRONG_VERSION_NUMBER` | TLS to plaintext port or plaintext to TLS port | DR `tls.mode` vs app doing its own TLS (double TLS) or PeerAuthentication mismatch |
| `handshake_failure` / `NO_SHARED_CIPHER` / `protocol_version` | Cipher/TLS version mismatch (legacy mainframe/MQ endpoints TLS1.0/1.1; JDK update disabled them) | New base image/JDK? `jdk.tls.disabledAlgorithms` change |
| `CERTIFICATE_VERIFY_FAILED` at sidecar | Sidecar can't trust target: missing `caCertificates` in DR, or mesh root mismatch across clusters | Multi-cluster / migration? |
| Gateway SDS: `failed to fetch secret`, `Secret is not supplied by SDS` | `credentialName` secret missing/wrong namespace/wrong keys (`tls.crt`/`tls.key`) | cert-manager logs; secret rotation time |
| istiod `CA` / `csr` / `failed to sign` errors | Istio CA issue → workload certs not renewed (24h default) → mesh-wide UF TLS after ~24h | istiod logs, plugged CA (Key Vault/cert-manager istio-csr) |

## 3. Expiry-specific patterns
- Errors start at an exact clock time across many callers at once → cert `NotAfter` (look for the time in messages: `NotAfter: Sat Oct 31 15:00:00 UTC 2026`).
- Errors start ~24h after istiod/CA trouble → workload cert expiry.
- Errors only from pods started after time X → new pods got new/bad cert or truststore; old pods cached good session.
- Java caches TLS sessions; failures may appear only on new connections (after pool recycle) → gradual rise.

## 4. cert-manager / Key Vault
- `{ns}:cert-manager` `Failed to`/`Order failed`/`challenge` errors before expiry date → renewal failure (ACME DNS/HTTP challenge, issuer creds).
- Key Vault-sourced certs via CSI: `secrets-store` mount errors; rotation poll interval delays.

## 5. Confirming without cluster access
Cert content (issuer, NotAfter, SAN) isn't in logs unless printed by exceptions. Java with `-Djavax.net.debug` is rarely on. Use the exception text; if not enough, escalation ask: `openssl s_client -connect host:port -servername host` from a pod/jump host, `istioctl proxy-config secret <pod>`, `kubectl get certificate -A`.
