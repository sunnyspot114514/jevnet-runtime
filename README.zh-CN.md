# JevNet Runtime

[![CI](https://github.com/sunnyspot114514/jevnet-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/sunnyspot114514/jevnet-runtime/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

[🇺🇸 English](README.md) | [🇨🇳 中文](README.zh-CN.md)

**一个放在 AI Agent 与真实世界之间的持久化副作用 Runtime。**

模型可以提出 tool call；JevNet Runtime 决定这个 Proposal 是否有资格变成真实、可持久化的外部动作。

> **模型负责提议。Runtime 负责授权、执行、观察与提交。**

可复用 runtime 与具体模型无关。**Jev 是这个项目的研究起点，不是 runtime package 的依赖。**

## 60 秒跑起来

```bash
git clone https://github.com/sunnyspot114514/jevnet-runtime.git
cd jevnet-runtime
python -m pip install -e .
python -m sar_runtime demo
```

你会看到类似输出：

```text
1) Correlated model approval does not override capability policy
   semantic votes: APPROVE / APPROVE / APPROVE
   tool: filesystem.chmod -> permission_change
   DAR issued: False

2) Allowed local capability executes through durable runtime
   external effects: 1
   COC status: SUCCEEDED

3) Restart/replay does not duplicate the effect
   same COC: True
   external effects after restart: 1

4) Approval seam fails closed
   no answerer -> unavailable
   grants authority: False
```

这个 demo **不需要 API key**。

## 它解决什么问题？

Agent 最大的风险之一，是把“模型说可以”直接等同于“系统真的可以执行”。

| 常见失败 | Runtime 机制 |
|---|---|
| 模型把危险工具判断成安全 | Runtime 自己维护 **Capability Manifest** |
| timeout 后重复执行同一个动作 | **Idempotency** + provider query |
| failover 后旧 worker 又醒了 | **Lease fencing** |
| 审批缺失或审批器坏了 | **Fail-closed approval** |
| 执行一半进程崩溃 | **Event-sourced durable replay** |
| 收到伪造 / 冲突回执 | **Reconciliation** |
| 某一个 replica 自称“最终结果” | **Replicated commit certificate** |

核心不是让模型永远不犯错，而是**限制模型犯错之后能获得多大的 authority**。

## 只需要记住 5 个盒子

```text
Agent / Model
     |
     v
  Proposal
     |
     v
Policy + Capability Gate
     |
     v
Durable Execution
     |
     v
Observed Outcome
     |
     v
Canonical Commit
```

底层对应：

```text
ToolCallProposal
DurableAuthorizationRecord
DispatchIntent
ProviderReceipt
CanonicalOutcomeCommit
```

完整 authority chain 见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 一个具体例子

Agent 提议：

```python
ToolCallProposal(
    tool_id="filesystem.chmod",
    args={"path": "deploy.sh", "mode": "755"},
)
```

哪怕三个语义 reviewer 都说 APPROVE，runtime 也会查自己的 manifest：

```text
filesystem.chmod
-> effect_class = permission_change
-> policy = forbidden
-> 不生成授权记录
-> 不产生外部 effect
```

**工具的 authority 属性属于 runtime registry，不属于模型。**

## 安装

推荐 Python 3.12。

```bash
python -m pip install -e .
python -m pytest -q
```

完整研究依赖：

```bash
python -m pip install -e ".[research]"
```

也可以运行：

```bash
./scripts/check.sh
```

或 Windows：

```powershell
.\scripts\check.ps1
```

## 最小 API

```python
from sar_runtime import (
    CapabilityManifest,
    CapabilityManifestEntry,
    InMemoryDurableStore,
    InMemoryLeaseCoordinator,
    InMemoryProvider,
    DurableRuntime,
    ToolCallProposal,
    build_proposal,
    build_vote,
    issue_dar,
)

manifest = CapabilityManifest(
    version=1,
    entries=[
        CapabilityManifestEntry(
            tool_id="local.write_file",
            effect_class="local_content_write",
            scope="local",
            reversible=True,
        )
    ],
    allowed_effects={"local_content_write"},
)

proposal = build_proposal(
    "P1",
    [ToolCallProposal("local.write_file", {"path": "notes.md"})],
)
votes = [
    build_vote("reviewer-1", proposal, True),
    build_vote("reviewer-2", proposal, True),
]

dar = issue_dar(
    proposal=proposal,
    votes=votes,
    threshold=2,
    manifest=manifest,
    action_id="ACT-1",
    auth_id="AUTH-1",
    idempotency_key="IDEM-1",
    auth_generation=1,
)

store = InMemoryDurableStore()
leases = InMemoryLeaseCoordinator()
provider = InMemoryProvider()
runtime = DurableRuntime(manifest)

runtime.persist_dar(store=store, stream_id="ACT-1", dar=dar)
coc = runtime.recover_action(
    store=store,
    stream_id="ACT-1",
    provider=provider,
    leases=leases,
    resource_id="workspace",
    owner_id="replica-1",
)
```

当前 in-memory 实现是 reference backend。真实项目可以通过同一接口替换成 SQLite/Postgres、HTTP provider、Redis/etcd lease。

## 借鉴 DSH 的 Harness 设计

这个 package 借鉴了 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 的几个架构思想，但没有复制它的实现：

- **service / plugin seam**：provider、store、lease、runtime 可以替换，不焊死在核心里；
- **event-sourced session**：durable record 从 append-only log replay，而不是相信进程内状态；
- **fail-closed approval**：没有 answerer、answerer 报错、结果不合法，都不会自动放行；
- **per-call policy**：执行边界在每次 capability call 时解析，而不是让 provider 保留一份全局可变权限状态。

JevNet Runtime 刻意比 DSH 小得多：它不试图复刻完整 Agent Loop、UI、MCP、sandbox 或插件生态。

设计对照见 [docs/DSH_INSPIRATION.md](docs/DSH_INSPIRATION.md)。

## Plugin / Service 组合

默认 Harness 由可替换 service 组成：

```python
from sar_runtime import build_default_harness

harness = build_default_harness(manifest)
print(harness.topology())
```

默认包含：

```text
manifest
backing_store
event-sourced store
provider
lease coordinator
durable runtime
```

Plugin 只有在依赖 service 全部存在后才会激活。缺依赖或重复 provider 都会直接报错，不会静默降级。

## Event-Sourced State

`EventSourcedStore` 会把 runtime 状态写成 append-only event：

```text
runtime/DurableAuthorizationRecord
runtime/DispatchIntent
runtime/ProviderReceipt
runtime/ReconciliationRecord
runtime/CanonicalOutcomeCommit
```

进程重启以后，runtime 从 durable records + provider reality 恢复，不依赖之前“记得自己做到哪一步”。

## Approval 默认 Fail Closed

`ApprovalService` 的结果是闭集：

```text
allowed-once
rejected
cancelled
unavailable
```

只有 `allowed-once` 会真正授予 authority。没有 answerer 或 answerer 异常都会得到 `unavailable`。

## 已经实现什么？

- Capability Manifest
- distinct-voter authorization quorum
- Durable Authorization Record
- DurableStore interface
- EventSourcedStore
- ProviderAdapter interface
- LeaseCoordinator interface
- idempotency
- fencing
- crash recovery
- receipt reconciliation
- Canonical Outcome Commit
- replicated commit certificate helper
- plugin/service registry
- fail-closed approval seam
- CLI demo

Reference backend：

- `InMemoryDurableStore`
- `InMemoryProvider`
- `InMemoryLeaseCoordinator`
- `EventSourcedStore`

## 为什么这些设计值得继续做？

使用这个 runtime **不需要先读研究历史**。

和当前架构直接相关的几条结果：

- 三个相同 Jev reviewer 在两个不同 frozen benchmark 中都曾一致误批真实 `chmod` 权限修改。
- fresh benchmark 中，Planner + Capability Manifest 做到 **24/24 authorization 正确**；Planner 自己的 tool selection 并不完美。
- 10,000-action crash/replay stress test 中：**0 unauthorized effect、0 missing authorized effect、0 replay digest drift**。
- reduced 5-replica / quorum-3 / 3-ballot checker 穷尽了 **442,524 states / 1,818,882 transitions**，在声明的有限模型内没有 conflicting chosen COC。

这些是研究证据，不是 production guarantee。

完整研究历史见 [RESEARCH_INDEX.md](RESEARCH_INDEX.md)。

## 仓库结构

```text
sar_runtime/              可复用 runtime package
docs/                     架构与设计说明
scripts/                  repo checks
test_sar_runtime_*.py     package-level tests

RESEARCH_INDEX.md         研究记录入口
ROUND*.md                 每轮详细报告
replicated_log_*.py       consensus / model-check 实验
jev_authorizer_*.py       frozen Jev authorization 实验
flygraph_*.py             历史 topology/connectome 实验
```

根 README 刻意不再解释完整“前世今生”。

## 它不是什么？

JevNet Runtime 当前还是 **research prototype / developer preview**。

它还不是：

- production sandbox；
- 完整 Agent framework；
- DSH、LangGraph、Claude Code 或 OS security boundary 的替代品；
- 完整 Paxos/Raft 实现；
- “三个相同模型投票就等于三份独立证据”的证明；
- “已经解决 LLM 幻觉”的项目。

## Roadmap

- SQLite / Postgres `DurableStore`
- HTTP/API `ProviderAdapter`
- Redis/etcd 风格 `LeaseCoordinator`
- compensation / Saga interface
- provider capability attestation
- crash-safe replicated-log backend
- 模型 adapter 标准化成 `ToolCallProposal` / `AuthorizationVote`

## 研究历史

这个项目确实是从 Jev topology / connectome 实验一路转过来的。

那些实验仍然保留，因为它们直接暴露了 state loss、soft probability provenance leakage 等问题，最终推动了现在的 runtime 结构。

但它们已经不是首页主线。

**第一次来看这个仓库，先看 Runtime；只有想追溯推导过程时再看研究记录。**

## 贡献与安全

- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)

## License

Apache License 2.0。详见 [LICENSE](LICENSE)。
