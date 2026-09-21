# Research Index / 研究记录

[🇺🇸 English](README.md) | [🇨🇳 中文说明](README.zh-CN.md)

The root README focuses on the reusable runtime and strongest current evidence.
This file indexes the main experiment reports.

| Stage | Report | Main question |
|---|---|---|
| Architecture Zoo | [ARCHITECTURE_ZOO_FINDINGS.md](ARCHITECTURE_ZOO_FINDINGS.md) | Which Jev information-flow topologies preserve state? |
| FlyGraph | [FLYGRAPH_NONSAFETY_FINDINGS.md](FLYGRAPH_NONSAFETY_FINDINGS.md) | Can a real MaleCNS motif act as a message-passing prior? |
| Round 2 | [ROUND2_FINDINGS.md](ROUND2_FINDINGS.md) | Do non-safety tasks reproduce the topology findings? |
| Round 3 | [ROUND3_RUNTIME_FINDINGS.md](ROUND3_RUNTIME_FINDINGS.md) | Why must soft output be separated from canonical state? |
| Round 4 | [ROUND4_STATE_RUNTIME_FINDINGS.md](ROUND4_STATE_RUNTIME_FINDINGS.md) | Conflict, revocation, staleness, transaction, COC |
| Round 5 | [ROUND5_CRASH_SAGA_FINDINGS.md](ROUND5_CRASH_SAGA_FINDINGS.md) | Crash recovery, timeout ambiguity, compensation |
| Round 6 | [ROUND6_DISTRIBUTED_AUTH_FINDINGS.md](ROUND6_DISTRIBUTED_AUTH_FINDINGS.md) | Cross-agent authority, quorum, fencing, revocation |
| Round 7 | [ROUND7_REPLICATED_LOG_FINDINGS.md](ROUND7_REPLICATED_LOG_FINDINGS.md) | Replicated COC and TLA+ |
| Round 8 | [ROUND8_FIVE_REPLICA_JEV_QUORUM_FINDINGS.md](ROUND8_FIVE_REPLICA_JEV_QUORUM_FINDINGS.md) | Five replicas, reconfiguration, liveness, Jev quorum |
| Round 9 | [ROUND9_CORRELATED_AUTH_POR_FINDINGS.md](ROUND9_CORRELATED_AUTH_POR_FINDINGS.md) | Correlated semantic error + certificate reduction |
| Round 10 | [ROUND10_END_TO_END_FINDINGS.md](ROUND10_END_TO_END_FINDINGS.md) | End-to-end runtime composition |
| Round 11 | [ROUND11_CAPABILITY_MANIFEST_FINDINGS.md](ROUND11_CAPABILITY_MANIFEST_FINDINGS.md) | Capability Manifest + 3-ballot exhaustive checker |
| Round 12 | [ROUND12_RUNTIME_PACKAGE_FINDINGS.md](ROUND12_RUNTIME_PACKAGE_FINDINGS.md) | Reusable model-agnostic runtime package |

## Formal / distributed artifacts

- [ReplicatedCOC.tla](ReplicatedCOC.tla)
- [REPLICATED_COC_FORMAL.md](REPLICATED_COC_FORMAL.md)
- [replicated_log_5node_3ballot_reduced.py](replicated_log_5node_3ballot_reduced.py)
- [replicated_log_certificate_por.py](replicated_log_certificate_por.py)
- [membership_reconfiguration.py](membership_reconfiguration.py)
- [partition_liveness.py](partition_liveness.py)

## Frozen Jev authorization benchmarks

- [JEV_AUTHORIZER_BENCHMARK_V1.md](JEV_AUTHORIZER_BENCHMARK_V1.md)
- [JEV_AUTHORIZER_BENCHMARK_V2.md](JEV_AUTHORIZER_BENCHMARK_V2.md)
- [JEV_AUTHORIZER_BENCHMARK_V3.md](JEV_AUTHORIZER_BENCHMARK_V3.md)
- [JEV_CAPABILITY_BENCHMARK_V1.md](JEV_CAPABILITY_BENCHMARK_V1.md)
