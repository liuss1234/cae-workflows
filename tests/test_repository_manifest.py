from pathlib import Path

from tools.repository_manifest import README_PATH, expected_readme, load_workflows


REPOSITORY = Path(__file__).resolve().parents[1]


def test_registered_skills_exist():
    workflows = load_workflows()
    registered = {workflow["name"] for workflow in workflows}
    discovered = {path.parent.name for path in (REPOSITORY / "skills").glob("*/SKILL.md")}
    assert registered == discovered


def test_registered_cli_entries_exist():
    for workflow in load_workflows():
        scripts = REPOSITORY / "skills" / workflow["name"] / "scripts"
        for entry in workflow.get("cli_entries", []):
            assert (scripts / (entry + ".py")).is_file()


def test_readme_workflow_table_is_current():
    content = README_PATH.read_text(encoding="utf-8")
    assert content == expected_readme(content, load_workflows())
