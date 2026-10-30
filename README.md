# quality-gate —— AI Agent 日常开发质量门禁

> **一句话：开发任务完成后，让 AI 按改动范围和风险做「真实运行的功能验证 + 分级代码审查」，产出带证据、绑定代码版本的质量报告；团队模式下每次审查自动沉淀为可回访的案例。**

它不是上线前的全量测试平台，而是融入日常开发的质量底线。核心设计：

> **固定质量底线 + 按开发范围选择验证模块 + 根据风险决定审查深度。**

简单 CRUD 十几分钟收口；触及权限、公共组件、跨服务流程的任务自动升级为完整门禁。

## 它替你回答三个问题

| 你担心的 | 它的做法 |
| --- | --- |
| AI 说"做好了"，真的能跑吗 | 接口真实调用、页面真实交互、数据与库里核对——**只读代码不算验证** |
| 会不会为了省事漏测 | 跳过的检查必须标「不适用 / 未测试」并写理由，报告里一眼可见，不得虚报通过 |
| 这套东西到底有没有用 | 每次审查自动建案例、验收后回访，定期用真实数据复盘迭代规则 |

## 两个仓库的关系

```
quality-gate-skill（本仓库）          quality-gate-cases
规则与工具源                          案例数据中心（Issue 即案例）
SKILL.md + qg-feedback 脚本          每次审查自动写入，只存数据不放代码
使用者 git pull 即升级                维护者定期导出分析，反哺规则迭代
```

## 快速开始（使用者，约 5 分钟）

### ① 克隆

```bash
# macOS / Linux
git clone http://git.tsintergy.com:8070/personal-warehouse/quality-gate/quality-gate-skill.git ~/tools/quality-gate-skill
```

```cmd
:: Windows
git clone http://git.tsintergy.com:8070/personal-warehouse/quality-gate/quality-gate-skill.git %USERPROFILE%\tools\quality-gate-skill
```

> 后文默认用约定路径 `~/tools/quality-gate-skill`（Windows 为 `%USERPROFILE%\tools\quality-gate-skill`）。**克隆到了别处？** 在克隆目录执行 `mkdir -p ~/tools && ln -s "$(pwd)" ~/tools/quality-gate-skill` 对齐，或把后文路径替换为实际位置。

### ② 接入你的 Agent（三选一，命令分平台）

**Claude Code**

```bash
ln -s ~/tools/quality-gate-skill ~/.claude/skills/quality-gate
ln -s ~/tools/quality-gate-skill ~/.agents/skills/quality-gate   # 跨 Agent 通用目录（可选）
```

**Codex**（新版从 `~/.codex/skills` 发现技能；`~/.agents/skills` 发现在部分版本有差异，两条都建最稳）

```bash
ln -s ~/tools/quality-gate-skill ~/.codex/skills/quality-gate
ln -s ~/tools/quality-gate-skill ~/.agents/skills/quality-gate
```

**DeepSeek Harness（dsh）及其他支持 AGENTS.md / 自定义系统提示的 Agent**

```bash
ln -s ~/tools/quality-gate-skill ~/.agents/skills/quality-gate
```

并在全局/项目 `AGENTS.md`（或会话系统提示模板）注入触发规则：

```markdown
# 质量审查协议（quality-gate）
- 任何前后端/全栈开发任务完成后，或用户要求「质量审查 / 验证功能 / quality-gate」时：
  1. 读取 ~/tools/quality-gate-skill/SKILL.md，严格按其阶段 0→A→B→C→D 流程执行；
  2. 团队模式按 SKILL.md「案例记录与反馈闭环」一节调用 scripts/qg-feedback.py 创建待回访案例，输出案例编号与链接；
  3. 用户说「质量反馈 QG-xxx：…」时，调用 qg-feedback success|defect 更新原案例，不新建记录。
- 执行过的检查必须给出可核对结果；跳过的检查标「不适用/未测试」并写原因，不得虚报通过。
- 升级方式：cd ~/tools/quality-gate-skill && git pull。
```

**Windows 用户**：软链改用 Junction（无需管理员）——`mkdir "%USERPROFILE%\.claude\skills" 2>nul & mklink /J "%USERPROFILE%\.claude\skills\quality-gate" "%USERPROFILE%\tools\quality-gate-skill"`，其余目录同理。

### ③ 配令牌（团队模式；不配也能用，只是不建案例）

1. 打开 http://git.tsintergy.com:8070/-/profile/personal_access_tokens （头像 → Settings → Access Tokens）；
2. Name `quality-gate`，Expires 建议不超过一年，Scopes 只勾 **`api`**；
3. Create 后立刻复制令牌（20 位随机串，**本 GitLab 13.x 不带 `glpat-` 前缀，属正常**；只显示一次）；
4. 写入环境变量：

```bash
# macOS（zsh）
echo 'export QG_GITLAB_TOKEN="你的令牌"' >> ~/.zshrc && source ~/.zshrc
```

```cmd
:: Windows（重开终端生效）
setx QG_GITLAB_TOKEN "你的令牌"
```

GitLab 地址与案例库项目 ID 已预置在 `config/default.yml`，无需再配。**令牌只放环境变量**：不进代码、不进配置文件、不在群里转发；泄露回同页面 Revoke 重建。

### ④ 验证

```bash
python3 ~/tools/quality-gate-skill/scripts/qg-feedback.py whoami
```

输出 `连接成功: <你的用户名> @ http://git.tsintergy.com:8070（案例项目 7854）` 即就绪。

## 日常使用：你只有两个动作

**动作一：开发完成后触发审查。** 说「按 quality-gate 审查」「质量审查一下」「开发完帮我检查」。Agent 会先亮出本次审查计划（范围/风险/预算）再执行：真实功能验证 → 分级代码审查 → 修复回归 → 证据化报告；团队模式自动创建「待回访」案例，把**编号 + 链接**发给你。

**动作二：验收后回访（一句话）。** 在**任意** Agent 会话说：

```
质量反馈 QG-20261028-001：验收通过
质量反馈 QG-20261028-001：发现缺陷：空日期查询报 500
```

确认成功自动关单；发现缺陷时 Agent 会补记归因（原审查为什么没拦住、怎么防复发）。也可以在案例库网页回访（看板拖拽/改标签，见 cases 仓库 README），但**推荐 Agent 方式**——归因完整、防呆、自动关单。

其余全自动：团队模式探测（whoami）、建案、标签维护、统计导出。

## 常见疑问（FAQ）

- **回访成功的案例为什么还在看板 Open 列？** Open/Closed 是 GitLab 的 Issue 生命周期，与案例状态标签是两套东西；确认成功后脚本会自动关闭 Issue，关闭的案例仍计入统计。
- **不配令牌会怎样？** 单机模式：审查照常执行，只是不建案例。
- **纯文档/配置改动也要跑功能测试吗？** 不用——按改动性质执行匹配的检查（文档查格式内容、构建/CI 配置跑对应校验）。
- **一次审查要多久？** 等级软预算：轻量 5–10 分钟、常规 10–20、深度 20–40（高风险可突破但须说明）；必测项未完成不会因超时被报成通过。
- **怎么升级？会不会错过新版本？** 每次审查开始会自动运行版本检查（`check-update`），本地落后时 Agent 会当场提示新版号与升级命令——不需要自己盯版本。升级 = `cd ~/tools/quality-gate-skill && git pull`；技能内容在**会话启动时**加载，pull 后新开会话才稳定生效，当前会话想立即用新版可让 Agent 直接读取仓库里的 SKILL.md 全文执行。落后版本跑的审查不受影响，案例会如实记录当时使用的版本。
- **案例里的 Token / 客户数据安全吗？** 案例只存脱敏摘要，默认不上传完整 diff、Token、客户数据、未脱敏日志。

## 案例生命周期（看懂案例库）

| 状态 | 含义 | 统计口径 |
| --- | --- | --- |
| 待回访 | 审查已记录，等使用者验收反馈 | 不计比率 |
| 确认成功 | 验收后观察期内未发现问题 | 计入成功 |
| 发现遗漏缺陷 | 验收发现此前未识别的问题 | 计入缺陷，必须归因 |
| 未回访 | 观察期（默认 30 天）内无反馈 | 不计任何比率 |

## 维护者：规则怎么迭代

真实开发 → 质量审查 → 待回访案例 → 验收反馈 → 问题归因 → 规则改进（MR）→ 回归核对 → 新版发布 → 分桶观察验证（见下「迭代验证」）。

### 1. 汇总（手动或自动）

```bash
python3 ~/tools/quality-gate-skill/scripts/qg-feedback.py export --out cases.jsonl --mark-stale
```

输出状态/风险分布、拦截缺陷合计、遗漏缺陷案例清单 + 全量 JSONL。自动周报：仓库 **Settings → CI/CD → Variables** 加 `QG_GITLAB_TOKEN`（若 Masked 报格式错误就不勾——本实例令牌含 `-`，旧版字符集可能不让 mask；脚本不会打印令牌），再在 **Schedules** 建每周任务，`weekly-case-report` 自动产出报告到 artifacts。

### 2. 分析

把 `cases.jsonl` 交给 AI Agent 出改进提案，围绕四个标准问题：

- 哪类任务交付后仍出缺陷？→ 增加针对性检查规则
- 哪些检查从没拦过问题、还经常阻塞？→ 裁剪或调整执行条件
- 轻量档是否长期够用？→ 校准风险分级
- 哪些规则误报多？→ 收紧判定条件

遗漏缺陷案例重点看归因字段 `why_missed` 与 `rule_change_hint`；结合 `execution_metrics` 看成本差异。**比较两个版本时按任务类型和风险等级对照**，总量对比不可信；不以缺陷数量或 Token 消耗单一指标下结论。

### 3. 改规则

开分支改 `SKILL.md`，**同一提交内**完成三件事：升 `VERSION`（增强升中位号 / 裁剪升大位号 / 小修升末位号）；`CHANGELOG.md` 记一条（改了什么、依据哪个 QG 案例）；逐条核对 `regression-cases/cases.yml` 命中的行为没被改坏（MR 描述列出核对过的用例编号）。

### 4. 合入与发布

push 分支 → MR → 合并 `main`（受保护、禁 force push；单人可直接 push main，MR 的价值是留痕）→ `git tag v1.1.0 && git push origin v1.1.0`。同事 `git pull` 即升级。

### 迭代验证：怎么确定真的优化了

先说诚实的边界：小组本的案例量**永远无法统计证明**一次迭代有效（样本小、任务难度不均、执行模型还会变）。做法是两层验证 + 一条防自欺铁律。

**铁律：先预声明，再上线。** 每个改进提案/MR 必须先写「预期可观测变化」——哪个分桶的哪个指标、朝哪个方向、多少幅度。没有预声明的指标，事后总能找到一个碰巧变好的数字自欺。MR 模板已内置此栏：`.gitlab/merge_request_templates/规则迭代.md`。

**第一层：机制验证（改完当天，确定性）**——回答"规则能不能干活"：

- **回放测试**：拿触发原问题的场景重放（例：v1.3.2 用 `duration_seconds` 建案回放别名规整；四路径回访真机实测）；
- **历史案例重审**（加检查类规则适用）：用当初漏网的案例在新规则下纸面重审——拦得住历史案例是**必要条件**（拦不住说明规则写错，直接打回），不是充分条件；
- **regression-cases 清单逐条核对**：机制不回归。

**第二层：统计验证（新版上线后，趋势性）**——回答"实战净收益是否为正"。export 后按 `skill_version` 分组、以 `task_type × scope × risk_level` 分桶，看三个指标：

| 指标 | 算法 | 坑 |
| --- | --- | --- |
| 漏网率 | 同桶 escaped 案例数 ÷ 有回访结论的案例数 | 未回访案例剔除；这是唯一真正衡量"漏"的指标 |
| 误报代价 | `confirmed_false_positives` 数 + items 中 `confirmed: false` | 新规则最易出现"拦截数上涨但全是误报" |
| 成本 | 同桶 `elapsed_seconds` **中位数** | 用中位数不用平均（长尾会骗人）；必须同任务类型对比 |

**桶内案例 <5 个只当趋势线索，不下结论。**

**回滚线（预写在提案里）**：如"若同桶漏网率不降反升，或误报新增 >N，回滚本规则"。触发即回滚，灰区继续观察，不嘴硬。

**两条纪律**：一次迭代只改一个主题（一个 minor 一个主题，打包多个改动会让验证失效——效果对了不知谁的功，错了不知回滚谁）；裁剪型改动（删"从没拦过问题"的检查）要**反向盯防**——专盯被裁检查对应的缺陷类别是否开始漏网，其验证期比加规则更长。

### 铁律

**单次案例不直接改规则。** 修改要有案例证据支撑；证据不足的想法在技能仓库开「候选提案」Issue 留痕（标签 `候选提案`、标题带证据计数如 1/3、正文含草案/依据/采纳阈值），达到约定阈值再 MR 落规则，反证则关闭留痕。使用者不在本地修改公共规则，统一拉取正式版。

> 当前进度：**v1.3.0 冻结为试运行基线**——只修阻断问题与实现缺陷，攒 20–30 个覆盖各范围×各等级的案例后做首次正式复盘。

## 安全

- 令牌只放本地环境变量或 CI/CD Variables（Masked），**绝不入库**；
- 案例默认不上传完整 diff、客户数据、Token、Cookie、未脱敏日志；
- 验证默认在本地/测试环境执行，写操作用隔离测试数据；未经授权不得在生产做改删数据的验证。
