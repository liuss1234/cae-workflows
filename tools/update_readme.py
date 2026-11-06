# -*- coding: utf-8 -*-
"""Update or verify the generated workflow table in README.md."""

import argparse

from repository_manifest import README_PATH, expected_readme, load_workflows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail instead of updating when README is stale")
    args = parser.parse_args()
    content = README_PATH.read_text(encoding="utf-8")
    expected = expected_readme(content, load_workflows())
    if content == expected:
        print("README workflow table is current")
        return
    if args.check:
        raise RuntimeError("README workflow table is stale; run python tools/update_readme.py")
    with README_PATH.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(expected)
    print("Updated README workflow table")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("README update failed: " + str(error))
        raise SystemExit(1)
