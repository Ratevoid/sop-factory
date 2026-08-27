<div align="center">

# SOP Factory

**把重复任务，自动编译成可复用、可验证、确定性的 SOP。**

Turn repetitive work into reusable, verifiable, deterministic SOPs — automatically.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-79%20passing-brightgreen)]()
[![Codex](https://img.shields.io/badge/Codex-compatible-000?logo=openai)](https://openai.com/codex)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-compatible-df8e43?logo=anthropic)](https://www.anthropic.com/claude-code)
[![Cursor](https://img.shields.io/badge/Cursor-compatible-000?logo=cursor)](https://cursor.com)
[![MCP](https://img.shields.io/badge/MCP-ready-7C3AED)](https://modelcontextprotocol.io/)

[快速开始](#快速开始--quick-start) · [核心概念](#核心概念--core-concepts) · [内置配方](#内置配方--built-in-recipes) · [架构](#架构--architecture) · [AI Agent 集成](#ai-agent-集成--ai-agent-integration) · [贡献](#贡献--contributing)

</div>

---

## 这是什么 / What is this

SOP Factory 是一个**项目中立的确定性 SOP 运行时框架**。它的核心能力是：**把你手工执行过的一次性任务，自动编译成可复用、可验证、可审计的标准操作流程（SOP）**。

不再需要把操作步骤写在文档里然后手动执行——SOP Factory 会从源码和操作中学习，生成带覆盖矩阵、行为合同和证据链的能力包，下次相同任务直接确定性执行。

SOP Factory is a **project-neutral deterministic SOP runtime framework**. Its core capability: **compile one-off tasks you've done manually into reusable, verifiable, auditable Standard Operating Procedures — automatically**.

No more writing steps in docs then executing them by hand. SOP Factory learns from source and operations, produces capability packages with coverage matrices, behavior contracts, and evidence chains — then runs the same task deterministically next time.

---

## 为什么用 SOP Factory / Why

| 痛点 / Pain | SOP Factory 的解法 / Solution |
|---|---|
| 重复操作每次手动做，容易出错 | 编译成确定性 SOP，相同输入永远相同输出 |
| 操作步骤写在文档里，没人看也不更新 | 能力包自带证据链和覆盖矩阵，可自动验证 |
| AI Agent 执行任务不可控、不可复现 | 风险分级门控 + dry-run + 原子写入，每步可审计 |
| 工具和项目知识耦合，换项目就要重写 | 知识隔离设计：框架纯净，项目知识通过 Profile 注入 |
| 不知道一个操作是否真的"学会了" | 完成门禁：未覆盖的代码面和未知项会明确阻断完成声明 |

---

## 快速开始 / Quick Start

### 安装 / Install

```bash
# 需要 Python 3.11+
# Requires Python 3.11+
git clone https://github.com/Ratevoid/sop-factory.git
cd sop-factory/runtime
pip install -e .
```

### 查看可用配方 / List recipes

```bash
python sop.py recipe list --json
```

### 自然语言搜索配方 / Search recipes by natural language

```bash
python sop.py recipe search --request "验证项目配置" --json
```

### 检查当前环境 / Check status

```bash
python sop.py status --json
```

### 从源码学习，编译成 SOP 能力包 / Learn from source, compile into SOP

```bash
python sop.py source learn --contract my-contract.json --out ./learned-capability --apply
python sop.py source verify ./learned-capability --json
```

---

## 核心概念 / Core Concepts

### 🏭 SOP 工厂 / The SOP Factory

框架的核心是 `source.learn`——它把一个完整的源码定义域，编译成带以下结构的能力包：

The heart of the framework is `source.learn` — it compiles a complete source code domain into a capability package containing:

- **覆盖矩阵 / Coverage Matrix**：哪些代码行被哪些行为覆盖，哪些仍是未知
- **行为合同 / Behavior Contracts**：每个已验证行为的输入空间、目标空间、转换规则和实现证据
- **差分证据 / Differential Evidence**：参考输出 vs 候选输出的可复现对比
- **未知项门禁 / Unknown Gate**：未映射的代码面或未验证的行为会明确阻断"完成"声明

### 📋 配方 / Recipe

配方是一个确定性的、可注册的操作单元。每个配方有：

A recipe is a deterministic, registrable operation unit. Each recipe has:

- 稳定的 JSON 输入/输出 Schema
- 明确的风险等级（`read_only` / `write` / `high`）
- 完成检查标准
- 代表性测试夹具
- 写入操作默认 dry-run，支持原子提交和幂等重跑

### 🔌 Profile / Adapter / Contract

项目知识**不**打包在框架里，而是通过以下扩展点注入：

Project knowledge is **never** bundled in the framework — it's injected through extension surfaces:

- **Profile**：声明项目身份、路径指纹、能力列表
- **Adapter**：项目特定的发现和适配逻辑
- **Contract**：操作的输入/输出合同

这意味着同一个 SOP Factory 框架可以服务于完全不同的项目，互不污染。

This means the same SOP Factory framework can serve completely different projects without cross-contamination.

---

## 内置配方 / Built-in Recipes

框架自带 10 个通用核心配方，覆盖 SOP 生命周期的各个阶段：

The framework ships with 10 universal core recipes covering the SOP lifecycle:

| 配方 / Recipe | 风险 / Risk | 说明 / Description |
|---|---|---|
| `context.resolve` | read_only | 识别操作目标和当前运行工程 |
| `config.validate` | read_only | 验证 Profile 配置、能力声明与唯一性 |
| `directive.parse` | read_only | 解析自然语言请求的意图、风险和范围 |
| `project.capability-audit` | read_only | 盘点项目声明能力、兼容配方与外部验收门禁 |
| `delivery.audit` | read_only | 审计 ZIP/APK/目录的完整性、安全路径与交付污染 |
| `asset.inspect` | read_only | 检查位图尺寸、透明边界和 SHA-256 |
| `asset.normalize` | write | 按合同确定性归一化位图并生成验证报告 |
| `source.learn` | write | **把源码定义域编译成带覆盖门禁的能力包** |
| `source.verify` | read_only | 回读验证能力包的文件闭合、哈希与完成边界 |
| `framework.package` | high | 把完整运行时打包为不含项目知识的可复现框架 ZIP |

---

## 架构 / Architecture

```
sop-factory/
├── runtime/
│   ├── sop.py                  # CLI 入口 / CLI entry
│   ├── sop_factory/
│   │   ├── registry.py         # 配方注册与校验 / Recipe registry & validation
│   │   ├── retrieval.py        # 自然语言配方搜索 / Natural-language recipe search
│   │   ├── context.py          # 项目上下文识别 / Project context resolution
│   │   ├── directives.py       # 指令风险解析 / Directive risk parsing
│   │   ├── source_learning.py  # ★ 源码学习编译器 / Source learning compiler
│   │   ├── pipeline.py         # 确定性资源处理流水线 / Deterministic asset pipeline
│   │   ├── delivery_audit.py   # 交付物审计 / Delivery auditing
│   │   ├── framework_package.py # 框架打包与知识隔离 / Framework packaging & knowledge isolation
│   │   ├── profiles.py         # Profile 加载 / Profile loading
│   │   ├── contracts.py        # 合同加载与校验 / Contract loading & validation
│   │   ├── state.py            # 隐私友好的使用统计 / Privacy-friendly usage stats
│   │   ├── human_output.py     # 中文人类可读输出 / Chinese human-readable output
│   │   └── errors.py           # 稳定错误码 / Stable error codes
│   ├── tests/                  # 79 个测试 / 79 tests
│   ├── profiles/               # 空扩展点 / Empty extension surface
│   ├── contracts/              # 空扩展点 / Empty extension surface
│   └── pyproject.toml
├── skills/
│   ├── sop/                    # AI Agent 路由 Skill / AI Agent routing skill
│   └── learning-closeout/      # 学习收尾 Skill / Learning closeout skill
├── scripts/run-sop             # 启动脚本 / Launcher
├── .codex-plugin/plugin.json   # Codex 插件入口 / Codex plugin entry
└── FRAMEWORK_MANIFEST.json     # 确定性文件清单 / Deterministic file inventory
```

### 设计原则 / Design Principles

1. **确定性 / Deterministic**：相同输入 + 相同合同 → 字节级相同输出
2. **知识隔离 / Knowledge Isolation**：框架不含任何项目数据，零配置即可安全分发
3. **风险门控 / Risk Gates**：写入默认 dry-run，高风险操作需明确批准
4. **证据优先 / Evidence-First**：每个已验证行为必须有可执行证据，不接受"大概可以"
5. **可审计 / Auditable**：每次调用记录动作、风险、结果和累计次数（不记录请求内容）

---

## AI Agent 集成 / AI Agent Integration

SOP Factory 设计为**AI Agent 原生**——它不是一个独立的 GUI 应用，而是一个可以被任何支持 Skills 或 MCP 的 AI Agent 直接调用的确定性运行时。

SOP Factory is **AI Agent-native** — not a standalone GUI app, but a deterministic runtime callable by any AI Agent that supports Skills or MCP.

### 支持的平台 / Supported Platforms

| 平台 / Platform | 集成方式 / Integration | 状态 / Status |
|---|---|---|
| **OpenAI Codex** | `.codex-plugin/plugin.json` + Skills | ✅ 原生支持 / Native |
| **Claude Code** | Skills 目录 + `$sop` 命令调用 | ✅ 支持 / Supported |
| **Cursor** | MCP 服务器模式（通过 `sop.py` CLI 包装） | ✅ 支持 / Supported |
| **任何 MCP 兼容 Agent** | 包装 `sop.py --json` 为 MCP Tool | ✅ 支持 / Supported |
| **任何支持 Skills 的 Agent** | 直接挂载 `skills/` 目录 | ✅ 支持 / Supported |

### 工作原理 / How It Works

1. Agent 收到用户任务 → 调用 `$sop directive parse` 解析意图和风险
2. Agent 调用 `$sop recipe search` 搜索匹配的确定性配方
3. 找到唯一匹配 → Agent 调用对应配方（如 `source.learn`）执行
4. 执行结果是稳定 JSON → Agent 用 `human_output` 渲染给用户
5. 任务完成 → `learning-closeout` Skill 自动评估是否有可复用经验

### 作为 Codex 插件 / As a Codex Plugin

仓库根目录已包含 `.codex-plugin/plugin.json`，Codex 会自动识别并加载 `skills/` 下的 Skill。

The repo ships with `.codex-plugin/plugin.json` — Codex auto-detects and loads Skills from `skills/`.

### 作为 Claude Code Skill / As a Claude Code Skill

将 `skills/sop/` 目录复制到 Claude Code 的 skills 目录，或在 `.claude/settings.json` 中添加路径。

Copy `skills/sop/` into Claude Code's skills directory, or add the path in `.claude/settings.json`.

### 作为 MCP 服务器 / As an MCP Server

任何 `sop.py <command> --json` 调用都可以包装为 MCP Tool。输入是命令参数，输出是稳定 JSON Schema。

Any `sop.py <command> --json` call can be wrapped as an MCP Tool. Input = command args, output = stable JSON Schema.

---

## 示例 / Examples

### 把一个代码库编译成 SOP 能力包 / Compile a codebase into SOP

```json
// contract.json
{
  "schema": "sop.source-learning-contract.v1",
  "capability": {
    "id": "my-project-automation",
    "title": "My Project Automation",
    "closed_scope": "src/ and assets/ only"
  },
  "corpus_roots": [
    {"id": "source", "path": "./src", "role": "source"}
  ],
  "behaviors": [
    {
      "id": "build-assets",
      "title": "Build all assets deterministically",
      "status": "verified",
      "why": "Asset build is fully deterministic",
      "source_evidence": [{"root_id": "source", "path": "build/asset_builder.ts"}],
      "procedure": [{"action": "Run asset builder with contract"}],
      "contracts": [{"kind": "input_output", "schema": "asset-build.v1"}],
      "required_contract_kinds": ["input_output"],
      "required_paths": ["build/asset_builder.ts"],
      "tests": [
        {"id": "build-smoke", "kind": "runtime", "status": "pass",
         "execution_paths": ["build/asset_builder.ts"],
         "report": "fixtures/build-report.json",
         "assertions": {"output.count": 42}}
      ]
    }
  ],
  "surfaces": [
    {"id": "asset-pipeline", "title": "Asset Pipeline", "behavior_ids": ["build-assets"]}
  ],
  "excluded_code": [],
  "completion_policy": {
    "require_all_surfaces_verified": true,
    "require_all_code_files_mapped": true
  }
}
```

```bash
python sop.py source learn --contract contract.json --out ./my-capability --apply
# 输出包含 capability.json, coverage-matrix.json, corpus-manifest.json, unknowns.json 等
# Output includes capability.json, coverage-matrix.json, corpus-manifest.json, unknowns.json, etc.
```

---

## 测试 / Testing

```bash
cd runtime
python -m pytest tests/ -v
# 79 passed
```

---

## 贡献 / Contributing

欢迎贡献！请遵循以下原则：

Contributions welcome! Please follow these principles:

1. 新配方必须有稳定 JSON Schema、明确风险等级、代表性测试和完成标准
2. 写入操作必须支持 dry-run、原子提交和幂等重跑
3. 项目特定知识（路径、配置、业务逻辑）必须放在 Profile/Adapter/Contract 中，**不能**进入核心代码
4. 所有新代码必须附带测试

---

## 许可证 / License

[MIT](LICENSE) — 自由使用、修改和分发。

Free to use, modify, and distribute.

---

<div align="center">

如果这个项目对你有帮助，欢迎给个 ⭐ Star！

If this project helps you, a ⭐ Star is much appreciated!

</div>
