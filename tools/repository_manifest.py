# -*- coding: utf-8 -*-
"""Load and validate the repository's single workflow registry."""

from pathlib import Path
import json
import re


REPOSITORY = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPOSITORY / "workflows.json"
README_PATH = REPOSITORY / "README.md"
README_TABLE_START = "<!-- WORKFLOWS:START -->"
README_TABLE_END = "<!-- WORKFLOWS:END -->"
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def load_workflows():
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("workflows.json schema_version must be 1")
    workflows = data.get("workflows")
    if not isinstance(workflows, list) or not workflows:
        raise ValueError("workflows.json must contain a non-empty workflows list")

    names = set()
    for workflow in workflows:
        name = workflow.get("name")
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
            raise ValueError("invalid workflow name: %r" % name)
        if name in names:
            raise ValueError("duplicate workflow name: " + name)
        names.add(name)
        for key in ("summary", "boundary"):
            if not isinstance(workflow.get(key), str) or not workflow[key].strip():
                raise ValueError("workflow %s has no %s" % (name, key))
        entries = workflow.get("cli_entries", [])
        if not isinstance(entries, list) or any(not isinstance(entry, str) or not entry for entry in entries):
            raise ValueError("workflow %s has invalid cli_entries" % name)
        for key in ("self_test",):
            if key in workflow and not isinstance(workflow[key], str):
                raise ValueError("workflow %s has invalid %s" % (name, key))
        required_files = workflow.get("required_package_files", [])
        if not isinstance(required_files, list) or any(not isinstance(path, str) or not path for path in required_files):
            raise ValueError("workflow %s has invalid required_package_files" % name)
    return workflows


def render_workflow_table(workflows):
    lines = [
        "| 模块 | 用途 | 使用边界 |",
        "|---|---|---|",
    ]
    for workflow in workflows:
        name = workflow["name"]
        lines.append(
            "| [%s](skills/%s/SKILL.md) | %s | %s |"
            % (name, name, workflow["summary"], workflow["boundary"])
        )
    return "\n".join(lines)


def expected_readme(content, workflows):
    if content.count(README_TABLE_START) != 1 or content.count(README_TABLE_END) != 1:
        raise ValueError("README must contain exactly one workflow table marker pair")
    before, remainder = content.split(README_TABLE_START, 1)
    _, after = remainder.split(README_TABLE_END, 1)
    table = render_workflow_table(workflows)
    return before + README_TABLE_START + "\n" + table + "\n" + README_TABLE_END + after
