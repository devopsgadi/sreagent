# Playbook — Cassandra (DataStax Java driver 3.x/4.x, Spring Data Cassandra, Astra / managed)

Entry: `CS-*` signatures; outbound TCP 9042/9142; latency on read/write APIs.

## 1. Which layer failed

| Evidence | Layer | Meaning |
|---|---|---|
| CS-01 `AllNodesFailedException` / `NoNodeAvailableException` / `NoHostAvailableException` | Connectivity | Driver can't reach any node in local DC. Read the per-node causes inside the message (connection refused, auth, TLS, timeout) |
| CS-09 `Error while opening new channel` / control connection failed | Connectivity | Network, TLS, wrong contact points, local DC name wrong (`local-datacenter` mismatch → all nodes ignored) |
| CS-02 `DriverTimeoutException: Query timed out after PT2S` | Client | Request exceeded driver `basic.request.timeout`; coordinator didn't answer in time — node slow, network, or pool queueing |
| CS-03 `ReadTimeoutException` (received X of Y responses) | Server | Coordinator waited on replicas: slow replicas, GC, tombstones, large partitions |
| CS-04 `WriteTimeoutException` (writeType=SIMPLE/BATCH/CAS) | Server | Replicas slow acknowledging; BATCH/CAS more fragile |
| CS-05 `UnavailableException` (required N, alive M) | Server | Replicas down for chosen consistency (LOCAL_QUORUM with node(s) down) — fails fast, no wait |
| CS-10 `OverloadedException` | Server | Node shedding load |
| CS-08 `BusyConnectionException` / `BusyPoolException` | Client | Too many in-flight requests per connection; app concurrency spike or Cassandra slow → queue |
| CS-06 auth failures | Security | Password rotated; role dropped; secret changed (new RS hash) |
| CS-07 `unconfigured table` / keyspace missing | Schema/config | Wrong keyspace per env, migration not applied, release expects new table |

## 2. Server vs client vs network — quick tests
- **Many apps** using the same cluster fail at once → cluster/network side. One app → app config, its query patterns, or its pool.
- **ReadTimeout/WriteTimeout/Unavailable** carry the coordinator node IP. Same node repeatedly → that node is bad.
- **DriverTimeout without server exceptions** → network or client-side queueing (check CS-08, pod CPU throttling `DB-02`, GC `JVM-02`).
- Sidecar outbound TCP lines to 9042: `UF` → can't connect; long-lived connections normally show long `duration` at close; mass closes at one minute → node restart or network drop.
- After a rollout: new image changed driver version/config (consistency, timeouts, `local-datacenter`).

## 3. Query-shape causes (visible in app logs)
- Driver slow-query logger (`RequestLogger` / `QueryLogger`) lines with CQL and latency — group by statement.
- `ALLOW FILTERING`, `IN` with many keys, unbounded `SELECT` → heavy reads → ReadTimeout.
- Logged/unlogged BATCH across partitions → WriteTimeout `BATCH_LOG`.
- `Paging state` / large result warnings.

## 4. If Cassandra server logs are indexed (CS-11)
- `Scanned over N tombstones` / `TombstoneOverwhelmingException` → data model / deletes.
- `GCInspector` long pauses on a node at the same minute as timeouts.
- `MUTATION messages were dropped` / `READ messages were dropped` → overloaded node.
- `Compaction` backlog, `Writing large partition`.
- Node `DOWN`/`UP` gossip messages → exact outage window per node.

## 5. Spring Data Cassandra mapping
`CassandraConnectionFailureException` → CS-01/09; `CassandraReadTimeoutException`/`WriteTimeout` → CS-03/04; `CassandraInsufficientReplicasAvailableException` → CS-05; `CassandraInvalidQueryException` → CS-07; `QueryTimeoutException` → CS-02.

## 6. Output
Coordinator/node IPs, consistency level, statement (if logged), error class split (connectivity vs timeout vs unavailable), first-seen, blast radius. Escalation asks: `nodetool status`, node metrics, DBA review of hot partitions/tombstones.
