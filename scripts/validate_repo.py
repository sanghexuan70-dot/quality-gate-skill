#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库自检：结构完整、frontmatter 合法、版本号与 CHANGELOG 一致、JSON 文件可解析。"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
errors = []

skill_path = os.path.join(ROOT, "SKILL.md")
if not os.path.isfile(skill_path):
    errors.append("缺少 SKILL.md")
else:
    text = open(skill_path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m or "name: quality-gate" not in m.group(1) or "version:" not in m.group(1):
        errors.append("SKILL.md frontmatter 需包含 name: quality-gate 与 version")

version = ""
version_path = os.path.join(ROOT, "VERSION")
if os.path.isfile(version_path):
    version = open(version_path, encoding="utf-8").read().strip()
if not re.match(r"^\d+\.\d+\.\d+$", version):
    errors.append("VERSION 需为语义化版本 x.y.z")
else:
    changelog_path = os.path.join(ROOT, "CHANGELOG.md")
    changelog = open(changelog_path, encoding="utf-8").read() if os.path.isfile(changelog_path) else ""
    if f"## {version}" not in changelog:
        errors.append(f"CHANGELOG.md 缺少 ## {version} 的版本记录")

for rel in ("schemas/quality-case.schema.json", "examples/case.example.json"):
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        errors.append(f"缺少 {rel}")
    else:
        try:
            json.load(open(path, encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{rel} 不是合法 JSON: {e}")

if errors:
    print("\n".join("✗ " + e for e in errors))
    sys.exit(1)
print(f"✓ 仓库自检通过（版本 {version or '?'}）")
