# Playbook — Kafka (Apache Kafka / Confluent / Azure Event Hubs Kafka endpoint)

Entry: `KF-*` signatures; consumer "lag" or "messages not processed" tickets; producer timeouts; outbound TCP to 9092/9093/9094 or `*.servicebus.windows.net:9093`.

Lag itself is a metric, not a log. From Kibana you infer it from processing gaps, rebalance churn, and listener failures. State this as a gap unless lag exporter / Burrow / Event Hubs metrics are indexed.

## 1. Producer or consumer?
- Logger names: `org.apache.kafka.clients.producer.*` vs `consumer.*` / `ConsumerCoordinator` / `KafkaMessageListenerContainer`.
- Catalog lists topics produced/consumed.

## 2. Connectivity first
| Evidence | Meaning |
|---|---|
| KF-01 `Broker may not be available` / `Bootstrap broker disconnected` | Network/DNS/firewall to brokers, or broker down. Check other apps using same cluster at same time (blast radius) |
| Sidecar outbound TCP to broker port with `UF` / short duration / 0 bytes | Connect failing through mesh (ServiceEntry, egress, NetworkPolicy) |
| `PassthroughCluster` to broker IPs | Brokers outside registry — fine if ALLOW_ANY; breaks if switched to REGISTRY_ONLY |
| KF-04 SASL auth failed | Credential / SAS key rotated, Event Hubs connection string expired, JAAS config secret changed (new RS hash) |
| TLS-* to broker | Broker cert rotation / truststore (`tls-certs.md`) |
| KF-05 Topic/Group authorization | ACL changed or new consumer group name in release |

Advertised listeners: client connects to bootstrap fine, then fails to individual brokers (`node 1`, `node 2` hostnames unresolvable) → broker `advertised.listeners` not reachable from cluster (DNS/ServiceEntry). Look for `UnknownHostException` with broker hostnames.

## 3. Consumer group health
| Evidence | Meaning |
|---|---|
| KF-02 rebalance messages repeating every few minutes | Group instability — members joining/leaving (pod restarts, rollouts, HPA flapping, long processing) |
| KF-03 `poll timeout has expired` / `max.poll.interval.ms` / `CommitFailedException` | Processing a batch exceeds `max.poll.interval.ms` (slow downstream: DB, Cassandra, HTTP). Consumer kicked → rebalance → reprocessing → duplicates |
| `Member ... sending LeaveGroup` + pod graceful shutdown | Normal rollout; problem only if rebalances outlast rollout |
| `Partitions assigned: []` on some pods | More consumers than partitions; idle pods (not an error) |
| Session timeout / heartbeat failed without slow processing | JVM pauses (GC), CPU throttling, network blips |

Correlate rebalance timestamps with pod lifecycle (`k8s-from-logs.md`). A crash-looping consumer pod causes group-wide rebalance storms and stalls every partition, not just its own.

## 4. Message-level failures
| Evidence | Meaning |
|---|---|
| KF-08 `DeserializationException` | Poison pill / producer schema change / wrong topic. Spring `ErrorHandlingDeserializer` will route to DLT; without it, the container loops on the same offset (same offset repeated in logs = stuck partition) |
| KF-09 `ListenerExecutionFailedException`, `Backoff exhausted`, DLT publish | Business/dependency failure inside listener; read the cause chain |
| KF-11 Schema Registry errors | Registry unreachable/auth; new schema incompatible |
| KF-10 RecordTooLarge | Producer payload > `max.request.size` / broker `message.max.bytes` (Event Hubs 1MB) |
| Same `offset=` / `partition=` value logged repeatedly | Stuck consumer on one record → lag grows on that partition only |

## 5. Producer failures
| Evidence | Meaning |
|---|---|
| KF-06 `Expiring N record(s)` / `delivery.timeout.ms` | Can't reach leader in time (broker slow/unreachable, throttling — Event Hubs throughput units exceeded) |
| `not present in metadata after` | Topic missing or no permission to describe; wrong env topic name |
| KF-07 `NOT_LEADER_OR_FOLLOWER` bursts | Broker restart / partition reassignment (transient if resolves in seconds) |
| KF-12 `ProducerFencedException` | Two instances with same `transactional.id` (old + new pod overlap during rollout) |

## 6. Event Hubs specifics
- Endpoint `NAMESPACE.servicebus.windows.net:9093`, SASL_SSL PLAIN, username `$ConnectionString`.
- Throttling shows as produce latency/timeouts; `ServerBusy` text in some clients.
- Consumer group limit (20 standard) → join failures.

## 7. Output
Name topic, partition(s), group id, first failure time, whether stuck (same offset) vs slow vs disconnected, and blast radius (single app vs all clients of the cluster). Escalation asks: consumer group describe (lag per partition), broker health, Event Hubs metrics.
