# quality-gate —— 日常开发质量门禁（团队共享版）

融入日常开发的质量审查技能：每次开发结束后，按开发范围与风险生成本次专属审查计划，实际运行验证功能（接口实测 + 浏览器交互 + 逐项证据），按轻量/常规/深度分级做代码审查，修复后回归重验，报告绑定代码版本。团队模式下每次审查自动记录为案例，通过回访反馈持续迭代规则。

核心设计：**固定质量底线 + 按开发范围选择验证模块 + 根据风险决定审查深度。**

## 仓库结构

```
SKILL.md                        质量审查规则（唯一正式规则源，只经 MR 修改）
VERSION / CHANGELOG.md          当前版本与升级记录
config/default.yml              团队模式配置（不含令牌）
scripts/qg-feedback.py          案例反馈 CLI（GitLab Issues 后端）
scripts/validate_repo.py        仓库自检（CI 用）
schemas/quality-case.schema.json 案例记录结构
examples/case.example.json      案例示例
regression-cases/cases.yml      规则回归用例（改规则后核对行为未退化）
.gitlab-ci.yml                  自检流水线 + 周期案例汇总
```

## 安装（同事）

1. 克隆本仓库（建议固定目录）：

```bash
# macOS / Linux
git clone http://git.tsintergy.com:8070/personal-warehouse/quality-gate/quality-gate-skill.git ~/tools/quality-gate-skill
```

```cmd
:: Windows（CMD / PowerShell）
git clone http://git.tsintergy.com:8070/personal-warehouse/quality-gate/quality-gate-skill.git %USERPROFILE%\tools\quality-gate-skill
```

> 后文所有命令默认使用约定路径 `~/tools/quality-gate-skill`（Windows 为 `%USERPROFILE%\tools\quality-gate-skill`）。**若已克隆到其他位置**，在克隆目录里执行一条命令对齐即可：`mkdir -p ~/tools && ln -s "$(pwd)" ~/tools/quality-gate-skill`；或把后文出现的该路径整体替换为你的实际克隆位置。
2. 按你使用的 Agent 接入技能目录（见下），软链方式保证 `git pull` 即升级。
3. 配置个人访问令牌（PAT，每个同事自己建一个）：

   1. 打开 http://git.tsintergy.com:8070/-/profile/personal_access_tokens （右上角头像 → Settings → Access Tokens）；
   2. Name 填 `quality-gate`，Expires 按公司要求（建议不超过一年），Scopes 只勾 **`api`**——创建/更新案例 Issue 与标签所需，GitLab 没有更细粒度的 scope，`api` 即最小可用；
   3. 点 Create 后**立刻复制**令牌——20 位随机字符串，**本 GitLab（13.x）发放的令牌不带 `glpat-` 前缀，属正常现象**；页面只显示这一次；
   4. 写入环境变量（之后新开的终端和 Agent 会话自动带上）：

   **macOS（zsh）**：

   ```bash
   echo 'export QG_GITLAB_TOKEN="你的令牌"' >> ~/.zshrc
   source ~/.zshrc
   ```

   **Windows**：任选其一。`setx` 最简单（写入用户环境变量，**重开终端后生效**）：

   ```cmd
   setx QG_GITLAB_TOKEN "你的令牌"
   ```

   或 PowerShell 配置文件（每次会话自动设置）：

   ```powershell
   if (!(Test-Path $PROFILE)) { New-Item -ItemType File -Force $PROFILE }
   Add-Content $PROFILE '$env:QG_GITLAB_TOKEN = "你的令牌"'
   ```

   令牌只放本地环境变量：不写进代码、不写进 `config/default.yml`、不在聊天/群里转发；怀疑泄露回同一页面 Revoke 重建；到期前换新并更新环境变量。

   GitLab 地址与案例库项目 ID 已预置在 `config/default.yml`（http://git.tsintergy.com:8070 / 案例库项目 7854 = personal-warehouse/quality-gate/quality-gate-cases），无需另行配置；如需覆盖，用环境变量 `QG_GITLAB_URL` / `QG_CASES_PROJECT_ID`。

4. 验证：

```bash
# macOS / Linux
python3 ~/tools/quality-gate-skill/scripts/qg-feedback.py whoami
```

```cmd
:: Windows（一般用 python 而非 python3）
python %USERPROFILE%\tools\quality-gate-skill\scripts\qg-feedback.py whoami
```

## 接入各 Agent

技能本体就是 `SKILL.md` + 脚本，任何能读文件、跑 shell 的 Agent 都能用；差别只在技能目录和触发方式。下面的软链命令是 macOS / Linux 写法；**Windows 用 Junction 链接代替**（无需管理员权限，把 `~/` 换成 `%USERPROFILE%\`）：

```cmd
:: Windows 通用写法（先确保父目录存在再链接）
mkdir "%USERPROFILE%\.claude\skills" 2>nul & mklink /J "%USERPROFILE%\.claude\skills\quality-gate" "%USERPROFILE%\tools\quality-gate-skill"
```

### Claude Code

```bash
ln -s ~/tools/quality-gate-skill ~/.claude/skills/quality-gate    # Claude Code 官方技能目录
ln -s ~/tools/quality-gate-skill ~/.agents/skills/quality-gate   # 跨 Agent 通用目录（可选，多工具共享一份）
```

```cmd
:: Windows 等价写法
mkdir "%USERPROFILE%\.claude\skills" 2>nul & mklink /J "%USERPROFILE%\.claude\skills\quality-gate" "%USERPROFILE%\tools\quality-gate-skill"
mkdir "%USERPROFILE%\.agents\skills" 2>nul & mklink /J "%USERPROFILE%\.agents\skills\quality-gate" "%USERPROFILE%\tools\quality-gate-skill"
```

触发：说「按 quality-gate 审查」「质量审查一下」「开发完帮我检查」，或 `/quality-gate`。想强制「每次开发完必跑」，把下面的触发规则片段追加到 `~/.claude/CLAUDE.md`（全局）或项目 `CLAUDE.md`。

### Codex

```bash
ln -s ~/tools/quality-gate-skill ~/.codex/skills/quality-gate    # Codex 技能目录（推荐）
ln -s ~/tools/quality-gate-skill ~/.agents/skills/quality-gate   # 兼容路径：部分版本从该目录发现，两个都建最稳
```

```cmd
:: Windows 等价写法
mkdir "%USERPROFILE%\.codex\skills" 2>nul & mklink /J "%USERPROFILE%\.codex\skills\quality-gate" "%USERPROFILE%\tools\quality-gate-skill"
mkdir "%USERPROFILE%\.agents\skills" 2>nul & mklink /J "%USERPROFILE%\.agents\skills\quality-gate" "%USERPROFILE%\tools\quality-gate-skill"
```

新版 Codex 从 `~/.codex/skills` 发现技能（每个技能一个含 `SKILL.md` 的目录）；社区反馈部分版本对 `~/.agents/skills` 的发现行为有差异，建议两条都建。也可在 `~/.codex/AGENTS.md`（全局）或项目根 `AGENTS.md` 注入触发规则片段，效果等价。

### DeepSeek Harness（dsh）

dsh 同样以 SKILL.md 作为技能载体（「一切皆插件」，技能是本地目录中的可复用指令集）：

```bash
ln -s ~/tools/quality-gate-skill ~/.agents/skills/quality-gate   # dsh 兼容跨 Agent 技能目录
```

并在全局/项目 `AGENTS.md`（或会话系统提示模板）注入下面的触发规则片段；具体技能发现目录以你所用 dsh 版本的文档为准，路径不同时改软链目标即可。

### 触发规则注入片段（AGENTS.md / CLAUDE.md / 系统提示通用）

```markdown
# 质量审查协议（quality-gate）
- 任何前后端/全栈开发任务完成后，或用户要求「质量审查 / 验证功能 / quality-gate」时：
  1. 读取 ~/tools/quality-gate-skill/SKILL.md，严格按其阶段 0→A→B→C→D 流程执行；
  2. 团队模式按 SKILL.md「案例记录与反馈闭环」一节调用 scripts/qg-feedback.py 创建待回访案例，输出案例编号与链接；
  3. 用户说「质量反馈 QG-xxx：…」时，调用 qg-feedback success|defect 更新原案例，不新建记录。
- 执行过的检查必须给出可核对结果；跳过的检查标「不适用/未测试」并写原因，不得虚报通过。
- 升级方式：cd ~/tools/quality-gate-skill && git pull。
```

> 参考：公司 `fcr` 的 `install-skill` 也是同样的做法——装到 `~/.claude/skills` 与 `~/.agents/skills` 供 Claude Code / Codex 自动加载。Windows 下触发规则片段中的路径对应 `%USERPROFILE%\tools\quality-gate-skill`。

未配置团队变量时技能照常运行（单机模式），只是不创建案例。

## 使用

- 开发完成后对 Agent 说「按 quality-gate 审查」或「质量审查一下」。
- 审查结束自动创建**待回访**案例，Agent 输出案例编号与链接。
- 后续验收完，在任意会话回访：

```
质量反馈 QG-20261028-001：验收通过
质量反馈 QG-20261028-001：发现缺陷：空日期查询报 500
```

## 案例生命周期

| 状态 | 含义 | 统计口径 |
| --- | --- | --- |
| 待回访 | 审查已记录，等用户验收反馈 | 不计成功率/失败率 |
| 确认成功 | 验收后在观察期内未发现问题 | 计入成功 |
| 发现遗漏缺陷 | 验收发现此前未识别的问题 | 计入缺陷，必须归因 |
| 未回访 | 观察期（默认 30 天）内无反馈 | 结果未知，不计入任何比率 |

注意：审查中拦截并修复了真实缺陷、最终验收通过的，算**成功案例**，其价值在「拦截缺陷明细」，案例中单独记录。

## 维护者：规则怎么迭代

真实开发 → 质量审查 → 待回访案例 → 验收反馈 → 问题归因 → 规则改进（MR）→ 回归核对 → 新版发布。

1. **汇总**：`python3 scripts/qg-feedback.py export --out cases.jsonl --mark-stale`（也可依赖 CI schedule 自动产出）。
2. **分析**：按版本/范围/风险/缺陷类型统计，回答——哪类任务交付后仍出缺陷？哪些检查从未拦截问题还常阻塞？轻量档是否长期够用？某版本改规则后某类缺陷是否减少（注意按任务类型对照，总量对比不可信）？
3. **提案**：改进以 MR 提交，描述附案例证据与命中的 regression-cases 编号；**单次案例不得直接改规则，使用者本地不改公共规则**。
4. **发布**：合入后更新 VERSION、CHANGELOG，打 tag（v1.0.0…），同事 `git pull` 即升级。

分支规则：`main` 为开发版（所有修改走 MR），tag 为正式版；每个案例记录运行时 Skill 版本，保证可追溯。

## 安全

- `QG_GITLAB_TOKEN` 只放本地环境变量或公司批准的密钥管理，**绝不入库**。
- 案例默认不上传完整 diff、客户数据、Token、Cookie、未脱敏日志。
- 默认在本地/测试环境执行验证；未经授权不得在生产做写操作验证。

## 实施三阶段

1. **打通案例闭环**（现在即可）：同事接入 + 每次审查建案 + 回访，先保证数据真实完整。
2. **自动汇总**：配置 CI schedule 与变量（仓库 Settings → CI/CD → Variables 添加 `QG_GITLAB_TOKEN` 并勾 Masked，再建 schedule pipeline 触发 `.gitlab-ci.yml` 里的 `weekly-case-report`），周期产出分类报告。
3. **AI 辅助迭代**：定期让 AI 分析案例库提出规则增删与校准建议，维护者评审后 MR 发布。
