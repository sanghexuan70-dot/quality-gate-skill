#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quality-gate 案例反馈 CLI —— 把每次质量审查记录为 GitLab Issue 案例并维护回访状态。

命令:
  whoami                              验证令牌与 GitLab 连通性
  create --file case.json             创建「待回访」案例，输出案例编号与链接（--dry-run 只预览）
  success QG-ID [--note ...]          回访：验收通过 → 确认成功
  defect QG-ID --reason ...           回访：发现遗漏缺陷（--why-missed / --rule-hint 可选）
  list [--status ...]                 列出案例（--status 可选 待回访/确认成功/发现遗漏缺陷/未回访）
  export [--out x.jsonl] [--mark-stale]  导出全部案例与统计；--mark-stale 把过期待回访正式标记为未回访

配置（优先级：环境变量 > config/default.yml > 内置默认）:
  QG_GITLAB_URL         GitLab 根地址，如 https://gitlab.example.com
  QG_GITLAB_TOKEN       访问令牌（只放环境变量，绝不写进仓库）
  QG_CASES_PROJECT_ID   案例库项目数字 ID（推荐独立项目）
  QG_OBSERVATION_DAYS   观察期天数（默认 30），过期待回访按未回访统计

原则：提交失败只报告「案例尚未同步」，绝不谎称已入库。
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(REPO_ROOT, "config", "default.yml")

LABEL_ROOT = "QG"
LABEL_PENDING = "待回访"
LABEL_SUCCESS = "确认成功"
LABEL_DEFECT = "发现遗漏缺陷"
LABEL_NOFOLLOWUP = "未回访"
ALL_LABELS = [LABEL_ROOT, LABEL_PENDING, LABEL_SUCCESS, LABEL_DEFECT, LABEL_NOFOLLOWUP]

CASE_RE = re.compile(r"^QG-(\d{8})-(\d{1,6})$")
TITLE_ID_RE = re.compile(r"\[(QG-\d{8}-\d+)\]")
JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


class QGError(Exception):
    pass


# ---------- 配置 ----------

def load_flat_yml(path):
    """极简 key: value 解析，仅供本仓库的扁平配置，避免引入 pyyaml 依赖。"""
    cfg = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if not line or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                cfg[k.strip()] = v
    except OSError:
        pass
    return cfg


def get_config():
    cfg = load_flat_yml(CONFIG_PATH)
    cfg["gitlab_url"] = os.environ.get("QG_GITLAB_URL", cfg.get("gitlab_url", "")).rstrip("/")
    cfg["project_id"] = os.environ.get("QG_CASES_PROJECT_ID", cfg.get("project_id", ""))
    cfg["token"] = os.environ.get("QG_GITLAB_TOKEN", "")
    try:
        cfg["observation_days"] = int(
            os.environ.get("QG_OBSERVATION_DAYS", cfg.get("observation_days", "30")))
    except ValueError:
        cfg["observation_days"] = 30
    return cfg


def ensure_ready(cfg):
    missing = [n for n, v in (("QG_GITLAB_URL", cfg["gitlab_url"]),
                              ("QG_GITLAB_TOKEN", cfg["token"]),
                              ("QG_CASES_PROJECT_ID", cfg["project_id"])) if not v]
    if missing:
        raise QGError("未配置: " + "、".join(missing) + "（环境变量或 config/default.yml）")


# ---------- GitLab API ----------

def api(cfg, method, path, payload=None):
    url = f"{cfg['gitlab_url']}/api/v4{path}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("PRIVATE-TOKEN", cfg["token"])
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
            # GitLab 不同版本错误位置不同：新版在 message，13.x 部分错误（如 Label already exists）在 error
            msg = body.get("message") or body.get("error") or ""
            if isinstance(msg, (dict, list)):
                msg = json.dumps(msg, ensure_ascii=False)
        except Exception:
            msg = ""
        raise QGError(f"GitLab API {e.code}: {msg or e.reason}") from None
    except urllib.error.URLError as e:
        raise QGError(f"无法连接 GitLab: {e.reason}") from None


def ensure_labels(cfg):
    """先查后建：已存在的标签不再 POST（GitLab 13.11 的『Label already exists』藏在 error 字段且
    曾导致 create 中断）；新建标签必须带 color（该版本无 color 的创建会被拒）。"""
    existing, page = set(), 1
    while True:
        batch = api(cfg, "GET", f"/projects/{cfg['project_id']}/labels?per_page=100&page={page}")
        if not batch:
            break
        existing.update(l["name"] for l in batch)
        if len(batch) < 100:
            break
        page += 1
    for name in ALL_LABELS:
        if name not in existing:
            api(cfg, "POST", f"/projects/{cfg['project_id']}/labels",
                {"name": name, "color": "#6699cc"})


# ---------- 案例工具 ----------

def iid_from_case_id(case_id):
    m = CASE_RE.match(case_id or "")
    if not m:
        raise QGError(f"案例编号格式应为 QG-YYYYMMDD-NNN，收到: {case_id}")
    return int(m.group(2))


def case_id_of(issue):
    m = TITLE_ID_RE.search(issue.get("title") or "")
    return m.group(1) if m else f"#{issue.get('iid')}"


def status_of(issue):
    labels = issue.get("labels") or []
    for lab in (LABEL_SUCCESS, LABEL_DEFECT, LABEL_NOFOLLOWUP, LABEL_PENDING):
        if lab in labels:
            return lab
    return LABEL_PENDING


def record_of(issue):
    m = JSON_BLOCK_RE.search(issue.get("description") or "")
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def parse_dt(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


CN_SCOPE = {"frontend": "前端", "backend": "后端", "fullstack": "全栈"}
CN_RISK = {"light": "轻量", "regular": "常规", "high": "高风险"}
CN_TYPE = {"feature": "新功能", "bugfix": "缺陷修复", "refactor": "重构",
           "doc": "文档", "config": "配置", "other": "其他"}
CN_FV_RESULT = {"pass": "功能验证通过", "partial": "功能验证部分通过", "fail": "功能验证未通过"}
CN_ITEM_STATUS = {"fixed": "已修复", "accepted": "已接受", "deferred": "暂缓", "open": "未关闭"}
BUDGET_RANGE = {"light": "5–10 分钟", "regular": "10–20 分钟", "high": "20–40 分钟"}


def _cn(mapping, value):
    return mapping.get(value, str(value or "未知"))


def build_description(record):
    """案例 Issue 描述：上半部分给人读（一句话结论 / 导读 / 明细），下半部分 details 折叠放给脚本解析的 JSON。"""
    fv = record.get("functional_verification") or {}
    cr = record.get("code_review") or {}
    det = (cr.get("detected_findings") or cr.get("findings")) or {}
    op = cr.get("open_findings") or {}
    items = cr.get("items") or []
    intercepted = cr.get("intercepted_defects") or []
    metrics = record.get("execution_metrics") or {}
    code = record.get("code_version") or {}
    L = []

    # —— 一句话结论 ——
    open_known = sum(v for v in op.values() if isinstance(v, int))
    open_unknown = sum(1 for v in op.values() if v is None)
    conclusion = [_cn(CN_FV_RESULT, fv.get("result"))]
    if intercepted:
        order = ("P0", "P1", "P2", "P3")
        sevs = [d.get("severity", "?") for d in intercepted]
        top = min(sevs, key=lambda s: order.index(s) if s in order else 9)
        conclusion.append(f"拦截 {len(intercepted)} 项缺陷（最高 {top}）")
    else:
        conclusion.append("拦截 0 项")
    conclusion.append(f"未关闭 {open_known} 项" + (f"（待补录 {open_unknown} 项）" if open_unknown else ""))
    L.append("> **" + "｜".join(conclusion) + "**")
    L.append("")

    # —— 改了什么 ——
    L.append(f"**改了什么**：{record.get('task_summary', '')}"
             f"（{_cn(CN_TYPE, record.get('task_type'))} · {_cn(CN_SCOPE, record.get('scope'))}"
             f" · {_cn(CN_RISK, record.get('risk_level'))}审查 · Skill v{record.get('skill_version', '?')}）")
    if record.get("reported_symptom"):
        L.append(f"- 原始症状：{record['reported_symptom']}")
    if record.get("expected_behavior"):
        L.append(f"- 预期行为：{record['expected_behavior']}")
    commit = (code.get("commit") or "")[:8] or "未知提交"
    dirty = ""
    if code.get("uncommitted"):
        dirty = "，含未提交修改"
        if code.get("diff_fingerprint"):
            dirty += f"（指纹 {str(code['diff_fingerprint'])[:23]}…）"
    files = f"，改动 {len(code.get('changed_files') or [])} 个文件" if code.get("changed_files") else ""
    L.append(f"- 代码版本：{code.get('branch') or '未知分支'} @ {commit}{dirty}{files}")
    L.append("")

    # —— 验证了什么 ——
    executed = fv.get("executed") or []
    L.append(f"**验证了什么**（{len(executed)} 项）：")
    for e in executed[:8]:
        L.append(f"- {e}")
    if len(executed) > 8:
        L.append(f"- …等共 {len(executed)} 项")
    for na in (fv.get("not_applicable") or []):
        L.append(f"- ⏭️ 不适用：{na}")
    for b in (fv.get("blocked") or []):
        L.append(f"- ⚠️ 阻塞：{b}")
    L.append("")

    # —— 拦截明细 ——
    if intercepted:
        L.append("**拦截明细**（质量门禁提前发现、交付前已处理的问题）：")
        for d in intercepted:
            L.append(f"- 🔴 {d.get('severity', '?')}｜{d.get('type', '')}｜{d.get('description', '')}")
            if d.get("check_item"):
                L.append(f"  - 由「{d['check_item']}」拦下")
        L.append("")

    # —— 审查发现 ——
    open_note = f"｜未关闭 {open_known} 项" + (f"（另有 {open_unknown} 项待补录）" if open_unknown else "")
    if items:
        parts = []
        for sev in ("p0", "p1", "p2", "p3"):
            n = det.get(sev, 0)
            if n:
                st = "、".join(sorted({CN_ITEM_STATUS.get(i.get("status"), "处置未知")
                                       for i in items if (i.get("severity") or "").upper() == sev.upper()})) or "处置未知"
                parts.append(f"{sev.upper()}×{n}（{st}）")
        L.append("**审查发现**：" + (" · ".join(parts) if parts else "无") + open_note)
    else:
        det_s = " · ".join(f"{s.upper()}×{det.get(s, 0)}" for s in ("p0", "p1", "p2", "p3") if det.get(s))
        L.append("**审查发现**：" + (det_s or "无") + open_note)
    L.append("")

    # —— 成本 ——
    if metrics:
        bits = []
        if metrics.get("elapsed_seconds") is not None:
            bits.append(f"耗时 {round(metrics['elapsed_seconds'] / 60)} 分钟"
                        f"（{_cn(CN_RISK, record.get('risk_level'))}预算 {BUDGET_RANGE.get(record.get('risk_level'), '—')}）")
        if metrics.get("test_cases_executed") is not None:
            bits.append(f"用例 {metrics['test_cases_executed']}/{metrics.get('test_cases_planned') or '?'}")
        if metrics.get("retries") is not None:
            bits.append(f"重试 {metrics['retries']}")
        if metrics.get("independent_agents_used") is not None:
            bits.append(f"子代理 {metrics['independent_agents_used']}")
        tk = metrics.get("input_tokens")
        bits.append("Token 未知" if tk is None else f"Token 入{tk}/出{metrics.get('output_tokens') or '?'}")
        if metrics.get("budget_exceeded"):
            bits.append(f"⚠️ 超预算：{metrics.get('budget_exceeded_reason') or '未说明'}")
        L.append("**成本**：" + "｜".join(bits))
        L.append("")

    # —— 机读区（折叠）+ 字段字典链接 ——
    L.append("<details><summary>📦 完整案例数据（JSON，供统计脚本解析，人不用看）</summary>")
    L.append("")
    L.append("```json")
    L.append(json.dumps(record, ensure_ascii=False, indent=2))
    L.append("```")
    L.append("</details>")
    L.append("")
    L.append("📖 各字段含义见 [cases 仓库 README「如何读懂一条案例」](http://git.tsintergy.com:8070/personal-warehouse/quality-gate/quality-gate-cases/-/blob/main/README.md)")
    return "\n".join(L)


def is_qg_case(issue):
    """案例识别不依赖单一标签：标题符合 QG-编号格式或带任一案例标签即算，
    防止网页手动编辑标签（整组替换会勾掉 QG）把案例从统计中挤掉。"""
    if CASE_RE.match(case_id_of(issue) or ""):
        return True
    labels = issue.get("labels") or []
    return any(l in labels for l in ALL_LABELS)


def fetch_all(cfg):
    issues, page = [], 1
    while True:
        batch = api(cfg, "GET",
                    f"/projects/{cfg['project_id']}/issues?state=all&per_page=50&page={page}")
        if not batch:
            break
        issues.extend(batch)
        if len(batch) < 50:
            break
        page += 1
    return [it for it in issues if is_qg_case(it)]


# ---------- 子命令 ----------

def cmd_whoami(args, cfg):
    ensure_ready(cfg)
    user = api(cfg, "GET", "/user")
    print(f"连接成功: {user.get('username', '?')} @ {cfg['gitlab_url']}（案例项目 {cfg['project_id']}）")
    return 0


def cmd_create(args, cfg):
    try:
        with open(args.file, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise QGError(f"读取案例文件失败: {e}")
    for field in ("skill_version", "scope", "risk_level", "task_summary", "task_type"):
        if not record.get(field):
            raise QGError(f"案例缺少必填字段: {field}")
    record.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    record.setdefault("outcome_status", "pending")

    if args.dry_run:
        print("[dry-run] 以下为将提交的案例内容（未调用 GitLab）：")
        print(build_description(record))
        return 0

    ensure_ready(cfg)
    ensure_labels(cfg)
    today = datetime.now().strftime("%Y%m%d")
    issue = api(cfg, "POST", f"/projects/{cfg['project_id']}/issues", {
        "title": f"[创建中] {record['scope']}/{record['risk_level']} {today}",
        "description": build_description(record),
        "labels": f"{LABEL_ROOT},{LABEL_PENDING}",
    })
    case_id = f"QG-{today}-{issue['iid']:03d}"
    record["case_id"] = case_id
    summary = (record.get("task_summary") or record.get("stack") or "").strip()
    if len(summary) > 40:
        summary = summary[:40] + "…"
    updated = api(cfg, "PUT", f"/projects/{cfg['project_id']}/issues/{issue['iid']}", {
        "title": f"[{case_id}] {LABEL_PENDING} | {record['scope']}/{record['risk_level']} | {summary}",
        "description": build_description(record),
    })
    if not args.no_writeback:
        record["issue_iid"] = issue["iid"]
        record["web_url"] = updated.get("web_url", "")
        with open(args.file, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    print(f"案例已创建: {case_id}")
    print(f"链接: {updated.get('web_url', issue.get('web_url', ''))}")
    print(f"回访方式: 在任意会话说「质量反馈 {case_id}: 验收通过」或「质量反馈 {case_id}: 发现缺陷: …」")
    return 0


def update_case(cfg, case_id, status_label, note):
    iid = iid_from_case_id(case_id)
    api(cfg, "PUT", f"/projects/{cfg['project_id']}/issues/{iid}",
        {"labels": f"{LABEL_ROOT},{status_label}"})
    if note:
        api(cfg, "POST", f"/projects/{cfg['project_id']}/issues/{iid}/notes", {"body": note})
    print(f"已更新 {case_id} → {status_label}")


def cmd_success(args, cfg):
    ensure_ready(cfg)
    note = f"## 验收回访：验收通过\n- 反馈: {args.note or '（未附说明）'}\n- 记录时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    update_case(cfg, args.case_id, LABEL_SUCCESS, note)
    if not args.keep_open:
        iid = iid_from_case_id(args.case_id)
        api(cfg, "PUT", f"/projects/{cfg['project_id']}/issues/{iid}", {"state_event": "close"})
        print(f"已关闭 {args.case_id}——确认成功即案例闭环结束（观察期内复发可 reopen 或新开案例；--keep-open 可保持打开）")
    return 0


def cmd_defect(args, cfg):
    ensure_ready(cfg)
    note = "\n".join([
        "## 验收回访：发现遗漏缺陷",
        f"- 缺陷: {args.reason}",
        f"- 为什么原审查没拦住: {args.why_missed or '（待补充）'}",
        f"- 规则改进提示: {args.rule_hint or '（待补充）'}",
        f"- 记录时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ])
    update_case(cfg, args.case_id, LABEL_DEFECT, note)
    print(f"{args.case_id} 保持打开直至缺陷处置完成；处置后可关闭（网页 Close、看板拖入 Closed 列、或评论 /close）")
    return 0


def cmd_list(args, cfg):
    ensure_ready(cfg)
    issues = fetch_all(cfg)
    if args.status:
        issues = [it for it in issues if status_of(it) == args.status]
    if not issues:
        print("（无案例）")
        return 0
    for it in sorted(issues, key=lambda x: x.get("created_at", ""), reverse=True):
        state = "已关闭" if it.get("state") == "closed" else "open"
        print(f"{case_id_of(it)}\t{status_of(it)}\t{state}\t{it.get('created_at', '')[:10]}\t{it.get('title', '')}")
    return 0


def cmd_export(args, cfg):
    ensure_ready(cfg)
    issues = fetch_all(cfg)
    now = datetime.now(timezone.utc)
    obs = timedelta(days=cfg["observation_days"])
    stats = {LABEL_PENDING: 0, LABEL_SUCCESS: 0, LABEL_DEFECT: 0, LABEL_NOFOLLOWUP: 0}
    by_risk, defects, intercepted_total, records = {}, [], 0, []
    for it in issues:
        rec = record_of(it)
        status = status_of(it)
        created = parse_dt(it.get("created_at"))
        stale = status == LABEL_PENDING and created and (now - created) > obs
        if stale:
            if args.mark_stale:
                api(cfg, "PUT", f"/projects/{cfg['project_id']}/issues/{it['iid']}",
                    {"labels": f"{LABEL_ROOT},{LABEL_NOFOLLOWUP}"})
                status = LABEL_NOFOLLOWUP
            else:
                status = LABEL_NOFOLLOWUP  # 统计口径：过期未反馈按未回访计
        stats[status] += 1
        by_risk[rec.get("risk_level", "未知")] = by_risk.get(rec.get("risk_level", "未知"), 0) + 1
        intercepted_total += len((rec.get("code_review") or {}).get("intercepted_defects") or [])
        if status == LABEL_DEFECT:
            defects.append(case_id_of(it))
        out = dict(rec)
        out["effective_status"] = status
        out["issue_iid"] = it.get("iid")
        out["web_url"] = it.get("web_url", "")
        records.append(out)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"案例总数: {len(records)}（观察期 {cfg['observation_days']} 天）")
    print("状态分布: " + " / ".join(f"{k} {v}" for k, v in stats.items()))
    print("风险分布: " + " / ".join(f"{k} {v}" for k, v in sorted(by_risk.items())))
    print(f"质量门禁拦截缺陷合计: {intercepted_total}")
    if defects:
        print("遗漏缺陷案例: " + ", ".join(defects))
    if args.out:
        print(f"已导出: {args.out}")
    return 0


def main():
    p = argparse.ArgumentParser(prog="qg-feedback", description="quality-gate 案例反馈 CLI（GitLab Issues 后端）")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("whoami", help="验证令牌与连通性")
    c = sub.add_parser("create", help="创建待回访案例")
    c.add_argument("--file", required=True, help="案例 JSON（结构见 schemas/quality-case.schema.json）")
    c.add_argument("--dry-run", action="store_true", help="只预览，不调用 GitLab")
    c.add_argument("--no-writeback", action="store_true", help="不把 case_id/链接写回案例文件")
    s = sub.add_parser("success", help="回访: 验收通过")
    s.add_argument("case_id")
    s.add_argument("--note", default="")
    s.add_argument("--keep-open", action="store_true", help="不自动关闭案例 Issue")
    d = sub.add_parser("defect", help="回访: 发现遗漏缺陷")
    d.add_argument("case_id")
    d.add_argument("--reason", required=True)
    d.add_argument("--why-missed", default="")
    d.add_argument("--rule-hint", default="")
    l = sub.add_parser("list", help="列出案例")
    l.add_argument("--status", default="", help="待回访/确认成功/发现遗漏缺陷/未回访")
    e = sub.add_parser("export", help="导出案例与统计")
    e.add_argument("--out", default="")
    e.add_argument("--mark-stale", action="store_true", help="把过期待回访正式改标为未回访")
    args = p.parse_args()
    cfg = get_config()
    handlers = {"whoami": cmd_whoami, "create": cmd_create, "success": cmd_success,
                "defect": cmd_defect, "list": cmd_list, "export": cmd_export}
    try:
        return handlers[args.cmd](args, cfg)
    except QGError as err:
        print(f"[失败] {err}", file=sys.stderr)
        print("案例尚未同步 / 操作未完成——请据实处理，不得视为已成功。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
