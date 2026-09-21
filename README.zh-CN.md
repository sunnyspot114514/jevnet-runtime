# JevNet Runtime：从 Jev 拓扑实验到 State-Aware Agent Runtime

[🇺🇸 English](README.md) | [🇨🇳 中文说明](README.zh-CN.md)

JevNet Runtime 最初的问题是：**Jev/SystemOne 能不能作为 typed computation primitive，放进 MLP、RNN、GNN、Transformer，甚至果蝇 connectome 形状的计算图里？**

真正做完这些实验以后，项目逐渐收敛到了一个更重要的系统结论：

> **模型应该拥有 Proposal Authority，而不应该默认拥有 State Authority。**

因此当前主线已经转向一个与具体模型解耦的 **State-Aware Runtime（SAR）**：typed proposal、Capability Manifest、持久授权、幂等与 fencing 执行、Observation reconciliation、Canonical Outcome Commit，以及 replicated commit safety。

可复用核心代码位于 [`sar_runtime/`](sar_runtime/)。Jev 现在是 runtime 上方可替换的 proposer / router / authorizer，而不是可信运行时本体。

## 当前状态

- **可复用的 `sar_runtime` Python 包已经在本地跑通。**
- Capability Manifest、quorum DAR、DurableStore、ProviderAdapter、LeaseCoordinator、持久恢复、idempotency、fencing、receipt reconciliation、COC 和 replicated commit certificate 已经做成模型无关接口。
- fresh capability benchmark：**Planner + Capability Manifest = 24/24 authorization 正确**；Direct semantic quorum 为 **22/24**，并再次复现了 `chmod` 权限修改被三个 Jev 一致误批的问题。
- Planner 的 tool-id vote 只有 **67/72** 正确，但 manifest gate 仍让 24 个最终授权全部正确，说明系统不需要先把 planner 变成完美 policy reasoner。
- reduced 5-replica / quorum-3 / 3-ballot checker 穷尽了 **442,524 个状态、1,818,882 条 transition**，在声明的 single-slot reduced model 内没有 conflicting chosen COC。
- 更宽泛的 crash/partition 模型仍明确标注为 **inconclusive**：它撞到 state cap，不能被解释成“证明安全”。
- 项目还包含真实 MaleCNS type-level / body-level connectome 的 Jev message-passing 实验。这些实验暴露了 soft probability provenance leakage，并直接推动了 canonical runtime gate。
- 当前提交的全部回归测试在本地通过。

## 核心思想

```text
自然语言意图
    |
    v
模型 / Jev Proposal
    |
    v
ToolCallProposal
    |
    v
Capability Manifest
    |
    v
确定性 Validation
    |
    v
Authorizer Quorum
    |
    v
Durable Authorization Record
    |
    v
Dispatch Intent + lease/fence + idempotency
    |
    v
真实外部 Effect
    |
    v
Provider Receipt
    |
    v
Reconciliation
    |
    v
Canonical Outcome Commit
    |
    v
Replicated Commit Certificate
    |
    v
Global Canonical State
```

模型可以不确定；runtime 决定模型解释什么时候真正获得 authority。

## 为什么需要这套 Runtime

长程 Agent 的失败不只是“最后一句话说错了”：

1. 不确定的模型输出过早变成 durable state；
2. timeout 后盲目重试同一个外部动作；
3. lease 已转移，旧 runtime replica 仍继续执行；
4. 授权在 command 飞行途中被撤销；
5. duplicate / forged / conflicting observation 乱序到达；
6. 本地 COC 被误当成全局 canonical truth；
7. 多个同模型 Authorizer 共享同一个语义盲点。

JevNet Runtime 把这些问题变成显式 runtime contract，而不是继续依赖“模型最好别犯错”。

## 可复用 Runtime 包

[`sar_runtime`](sar_runtime/) 当前提供：

```text
CapabilityManifest
DurableStore / InMemoryDurableStore
ProviderAdapter / InMemoryProvider
LeaseCoordinator / InMemoryLeaseCoordinator
RuntimeEngine
DurableRuntime
build_commit_certificate()
validate_commit_certificate()
```

核心包本身不依赖 Jev 或其他 LLM。

## 关键实验结果

### 同模型 Quorum 不能消除相关语义错误

三个完全相同的 Jev Authorizer 曾对真正的权限修改给出一致 APPROVE，且置信度约为 `P(APPROVE) ≈ 0.93`。

fresh benchmark 又用新的 chmod 措辞复现了同类 false authorization。

因此 2-of-3 可以抗一个 Byzantine/outlier vote，但不能抗三个模型共享的同一误区。

### Capability Manifest 能把共同错误变成无权限错误

Planner + Manifest 路径：

```text
filesystem.chmod
    -> permission_change
    -> forbidden
    -> no DAR
```

fresh benchmark：

| Pipeline | Authorization accuracy |
|---|---:|
| Direct semantic quorum | 22/24 |
| **Planner + Capability Manifest** | **24/24** |

Planner 本身并不完美；正确性来自缩小模型 authority，而不是假设 planner 完美。

### Durable Recovery

10,000-action stress test 中包括 6,093 次 crash 和 473 条重复 durable records。

最终：
- unauthorized effects = 0
- missing authorized effects = 0
- unauthorized COC = 0
- missing authorized COC = 0
- replay 后 canonical digest 漂移 = 0

### Idempotency 与 Fencing

- **Idempotency** 防同一 authorized action replay；
- **Fencing** 防旧 execution owner 在 lease handoff 后执行另一条 stale action。

### Replicated COC Safety

Reduced 5-replica / quorum-3 / 3-ballot checker：

```text
states       = 442,524
transitions  = 1,818,882
state cap    = 未触发
conflicting COC = 0
```

这是有限 single-slot safety result，不是完整 Paxos/Raft 证明。

## 仓库结构

```text
sar_runtime/
  types.py
  manifest.py
  authorization.py
  adapters.py
  provider.py
  store.py
  lease.py
  durable_runtime.py
  runtime.py
  consensus.py
  builders.py
  README.md

ROUND*.md
ReplicatedCOC.tla
ReplicatedCOC_*.cfg

jev_authorizer_*.py
jev_capability_*.py
replicated_log_*.py
flygraph_*.py
runtime_state_*.py
test_*.py
```

生成结果目录和 API secret 不提交到 Git。

## 快速开始

推荐 Python 3.12。

```bash
git clone https://github.com/sunnyspot114514/jevnet-runtime.git
cd jevnet-runtime
python -m pip install -e .
python -m pip install -e ".[research]"
python -m pytest -q
```

模型无关 runtime 可以直接使用，不需要 Jev。

Jev 研究实验使用本地、已 git-ignore 的 `.env`：

```text
TYPESAFE_API_KEY=...
```

## 研究记录

完整实验演化过程见 [RESEARCH_INDEX.md](RESEARCH_INDEX.md)。

从 topology analogues、FlyGraph、soft-state leakage，一直到 crash recovery、cross-agent authorization、replicated COC、Capability Manifest 和 runtime package，所有关键 round 都保留了独立报告和限制说明。

## 当前复现层级

仓库当前提供：
- runner / benchmark hash 冻结的 Jev authorization 实验；
- 模型无关 runtime 接口和 in-memory reference implementation；
- deterministic capability gate 与 quorum authorization；
- durable crash recovery；
- idempotent / fenced provider semantics；
- receipt reconciliation + COC；
- finite replicated-log safety checker；
- TLA+ single-slot COC specification；
- 真实 MaleCNS-derived graph experiments；
- runtime package 和 research invariants 的 regression tests。

当前**不声称**：
- production-grade consensus / storage correctness；
- 完整 Paxos/Raft 证明；
- 任意异步调度下的 liveness；
- Byzantine provider tolerance；
- 普适 semantic authorization accuracy；
- 同一个模型重复调用就是独立 evidence；
- 生物 connectome topology 普遍优于 random topology。

## 核心原则

> **概率系统负责提出解释；确定性、持久化的协议负责决定这些解释何时获得 authority。**

## 许可证

Apache License 2.0。详见 [LICENSE](LICENSE)。
