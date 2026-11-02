#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quality-gate 事件驱动回访·轮询引擎（第一期，无状态设计）

原则：**案例即数据库**——所有检查点/挂钩/观察期进度都存在案例 Issue 的 delivery 字段里，
每轮从案例当前状态推导动作，天然幂等，CI Runner 临时环境可任意重跑。

每轮做的事（对案例库每条 open 且非人工终态的案例）：
  1. 扫案例评论中的 /qg 指令（accept/defect/false-positive/close）→ 代为执行（有回复即不重复执行）
  2. 若无 delivery.mr：按案例 branch 锚点在全实例搜 MR（源分支精确匹配优先）→ 挂钩并记录
  3. 若已挂钩：拉 MR 状态，merged 且未记录 → 写入交付证据、起算观察期
  4. 观察期（merged_at 起算，轻量7/常规14/深度30 天）到期且无缺陷反馈 → 标「未回访（观察期满）」并关闭

人工优先：已有「确认成功/发现遗漏缺陷」标签的案例不动；/qg 指令执行结果与人工回访等价。

用法：python3 qg-poll.py once | status
"""
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("qgf", os.path.join(HERE, "qg-feedback.py"))
qgf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qgf)

OBSERVATION_DAYS = {"light": 7, "regular": 14, "high": 30}
MANUAL_STATES = {"确认成功", "发现遗漏缺陷"}
CMD_RE = re.compile(r"^/qg\s+(accept|defect|false-positive|close)\s+(QG-\d{8}-\d+)(?:\s+(.*))?", re.M)
QG_POLL_MARK = "<!-- qg-poll -->"


def parse_dt(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def save_case(cfg, case, rec, reason):
    """把自动事件写进案例（delivery + feedback_events）并留评论。"""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rec.setdefault("feedback_events", []).append(
        {"source": "qg-poll", "occurred_at": now, "note": reason})
    qgf.api(cfg, "PUT", f"/projects/{cfg['project_id']}/issues/{case['iid']}",
            {"description": qgf.build_description(rec)})
    qgf.api(cfg, "POST", f"/projects/{cfg['project_id']}/issues/{case['iid']}/notes",
            {"body": f"{QG_POLL_MARK}\n## 自动事件（qg-poll）\n{reason}\n- 时间: {now}"})


def find_mr(cfg, branch, case_created_at):
    """按源分支精确查询（无窗口遗漏）+ 时间过滤（交付必然晚于审查）：
    - merged 候选：merged_at >= 案例创建时间（审查先于交付），取最早合并的——即审查后的首次交付；
    - opened 候选：created_at >= 案例创建时间 - 3 天（MR 常在审查前后开出），取最新更新的；
    - 优先 merged（已发生的交付），否则 opened（待跟踪），都没有返回 None。
    长命分支多 MR 场景（feature-1.0.0-sanghx 20+ 个历史 MR）靠时间过滤避免错挂。"""
    try:
        mrs = qgf.api(cfg, "GET",
                      f"/merge_requests?state=all&source_branch={branch}&per_page=50")
    except Exception:
        return None
    merged_c = [m for m in mrs if m["state"] == "merged"
                and (m.get("merged_at") or "") >= case_created_at]
    if merged_c:
        return min(merged_c, key=lambda m: m.get("merged_at") or "")
    opened_c = [m for m in mrs if m["state"] == "opened"
                and (m.get("created_at") or "") >= (case_created_at or "")[:10]]
    if opened_c:
        return max(opened_c, key=lambda m: m.get("updated_at") or "")
    return None


def all_mrs(cfg):
    """兼容保留：全量 MR 拉取（发现逻辑已改用按分支精确查询，不再使用）。"""
    mrs, page = [], 1
    while True:
        batch = qgf.api(cfg, "GET",
                        f"/merge_requests?state=all&per_page=50&page={page}&order_by=updated_at&sort=desc")
        if not batch:
            break
        mrs.extend(batch)
        if len(batch) < 50 or page >= 10:
            break
        page += 1
    return mrs


def process_commands(cfg, case, rec, actions):
    """处理案例评论中的 /qg 指令；以「本引擎已回复 note-id」判重。"""
    notes = [n for n in qgf.api(cfg, "GET",
             f"/projects/{cfg['project_id']}/issues/{case['iid']}/notes?per_page=100")
             if not n.get("system")]
    done_ids = set()
    for n in notes:
        if QG_POLL_MARK in (n.get("body") or ""):
            m = re.search(r"executed note (\d+)", n["body"])
            if m:
                done_ids.add(int(m.group(1)))
    for n in notes:
        if n["id"] in done_ids or QG_POLL_MARK in (n.get("body") or ""):
            continue
        for m in CMD_RE.finditer(n.get("body") or ""):
            cmd, cid, arg = m.group(1), m.group(2), (m.group(3) or "").strip()
            if cid != qgf.case_id_of(case):
                continue
            cid_short = qgf.case_id_of(case)
            argv = {"accept": ["success", cid_short, "--note", arg or f"评论指令（{n['author']['name']}）"],
                    "close": ["close", cid_short, "--note", arg or "评论指令关闭"]}.get(cmd)
            if cmd == "defect":
                argv = ["defect", cid_short, "--reason", arg or "（评论未附描述）"]
            elif cmd == "false-positive":
                argv = ["false-positive", cid_short, "--finding", arg or "?"]
            if not argv:
                continue
            import contextlib, io
            sys.argv = ["qg-feedback"] + argv
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                qgf.main()
            qgf.api(cfg, "POST", f"/projects/{cfg['project_id']}/issues/{case['iid']}/notes",
                    {"body": f"{QG_POLL_MARK}\n已执行评论指令 `{cmd}`（executed note {n['id']}）：\n> {arg or '（无参数）'}\n{buf.getvalue().strip()}"})
            actions.append(f"{cid_short}: 执行评论指令 {cmd}")
    return actions


def run_once(cfg):
    actions = []
    for case in qgf.fetch_all(cfg):
        if case.get("state") == "closed":
            continue
        labels = set(case.get("labels") or [])
        rec = qgf.record_of(case)
        if not rec:
            continue
        cid = qgf.case_id_of(case)
        # 1) 评论指令（对任何 open 案例可用，包括已人工回访的——如 defect 推翻 accept）
        process_commands(cfg, case, rec, actions)
        if labels & MANUAL_STATES:
            continue
        delivery = rec.setdefault("delivery", {})
        branch = (rec.get("code_version") or {}).get("branch") or ""
        # 2) 挂钩发现（按分支精确查询 + 交付晚于审查的时间过滤）
        if not delivery.get("mr") and branch:
            mr = find_mr(cfg, branch, case.get("created_at") or "")
            if mr:
                delivery["mr"] = f"{mr['project_id']}:{mr['iid']}"
                delivery["mr_state"] = mr["state"]
                save_case(cfg, case, rec, f"挂钩 MR !{mr['iid']}（{mr['source_branch']} @ 项目 {mr['project_id']}，状态 {mr['state']}）")
                actions.append(f"{cid}: 挂钩 {delivery['mr']}")
                continue
        # 3) 状态推进
        if delivery.get("mr") and not delivery.get("merged_at"):
            pid, miid = delivery["mr"].split(":")
            mr = qgf.api(cfg, "GET", f"/projects/{pid}/merge_requests/{miid}")
            delivery["mr_state"] = mr["state"]
            if mr["state"] == "merged" and mr.get("merged_at"):
                merged_at = mr["merged_at"]
                days = OBSERVATION_DAYS.get(rec.get("risk_level"), 14)
                until = (parse_dt(merged_at) + timedelta(days=days)).isoformat(timespec="seconds")
                delivery.update({"status": "merged", "merged_at": merged_at, "observed_until": until})
                rec.setdefault("related_merge_requests", []).append({"mr": delivery["mr"], "merged_at": merged_at})
                save_case(cfg, case, rec,
                          f"关联 MR 已合并 → 交付状态 merged，观察期 {days} 天（至 {until[:10]}）。"
                          f"期间发现问题可评论 `/qg defect {cid} <描述>`。")
                actions.append(f"{cid}: MR merged → 观察期 {days} 天")
            elif mr["state"] == "closed":
                delivery["status"] = "closed_unmerged"
                save_case(cfg, case, rec, "关联 MR 关闭且未合并，案例保持待回访")
                actions.append(f"{cid}: MR closed_unmerged")
            continue
        # 4) 观察期收口
        if delivery.get("observed_until"):
            until_dt = parse_dt(delivery["observed_until"])
            if until_dt and datetime.now(timezone.utc) >= until_dt:
                delivery["observation_result"] = "no_feedback"
                save_case(cfg, case, rec,
                          f"观察期（至 {delivery['observed_until'][:10]}）结束，未收到缺陷反馈与人工回访 → "
                          f"标「未回访（观察期满，未收到缺陷反馈）」。注意：no_feedback ≠ success，后续发现问题仍可 reopen。")
                qgf.set_issue_labels(cfg, case["iid"], ["QG", "未回访"])
                qgf.api(cfg, "PUT", f"/projects/{cfg['project_id']}/issues/{case['iid']}", {"state_event": "close"})
                actions.append(f"{cid}: 观察期满 → 未回访(no_feedback)，关闭")
    return actions


def cmd_status(cfg):
    for case in qgf.fetch_all(cfg):
        rec = qgf.record_of(case)
        d = rec.get("delivery") or {}
        if d:
            print(f"  {qgf.case_id_of(case)}: mr={d.get('mr')} state={d.get('mr_state')} "
                  f"merged={ (d.get('merged_at') or '')[:10]} until={(d.get('observed_until') or '')[:10]}")
        else:
            print(f"  {qgf.case_id_of(case)}: （未挂钩）")


def main():
    cfg = qgf.get_config()
    qgf.ensure_ready(cfg)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "status":
        cmd_status(cfg)
    elif cmd == "once":
        for a in run_once(cfg):
            print(" ", a)
        print("轮询完成")
    else:
        print("用法: qg-poll.py once|status")
        sys.exit(2)


if __name__ == "__main__":
    main()
