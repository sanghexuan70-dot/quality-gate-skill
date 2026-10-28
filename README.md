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

1. 克隆本仓库（建议固定目录，如 `~/tools/quality-gate-skill`）。
2. 把技能接入 Agent 的技能目录（软链，便于 `git pull` 即升级）：

```bash
ln -s ~/tools/quality-gate-skill ~/.agents/skills/quality-gate
# 或 ZCode 技能目录：ln -s ~/tools/quality-gate-skill ~/.zcode/skills/quality-gate
```

3. 配置团队模式令牌（写入 shell profile）：

```bash
export QG_GITLAB_TOKEN="<个人访问令牌>"   # scope: api，只放本地环境变量
```

GitLab 地址与案例库项目 ID 已预置在 `config/default.yml`（http://git.tsintergy.com:8070 / 案例库项目 7854 = personal-warehouse/quality-gate/quality-gate-cases）；如需覆盖，用环境变量 `QG_GITLAB_URL` / `QG_CASES_PROJECT_ID`。

4. 验证：`python3 scripts/qg-feedback.py whoami`

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
2. **自动汇总**：配置 CI schedule 与变量，周期产出分类报告。
3. **AI 辅助迭代**：定期让 AI 分析案例库提出规则增删与校准建议，维护者评审后 MR 发布。
