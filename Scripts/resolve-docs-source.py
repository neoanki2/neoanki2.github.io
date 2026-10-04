#!/usr/bin/env python3
"""Select approved documentation without changing the app repository's gates."""
import argparse
import json
from pathlib import Path
import re
import subprocess


SOURCE_REPOSITORY = "neoanki2/neoanki2"


def github(path):
    return json.loads(subprocess.check_output([
        "gh", "api", f"repos/{SOURCE_REPOSITORY}/{path}"
    ], text=True))


def docs_tree(commit, api):
    tree = api(f"git/commits/{commit}")["tree"]["sha"]
    entries = api(f"git/trees/{tree}")["tree"]
    return next(entry["sha"] for entry in entries
                if entry["path"] == "docs" and entry["type"] == "tree")


def resolve(config, api=github):
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("Invalid documentation source configuration")
    if config.get("repository") != SOURCE_REPOSITORY:
        raise ValueError("Documentation source repository is not approved")
    source = config.get("source_sha", "")
    expected_tree = config.get("docs_tree_sha", "")
    for value in (source, expected_tree):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("Documentation source must use exact commit/tree hashes")
    run_id = config.get("documentation_run_id")
    pull_request = config.get("source_pull_request")
    if type(run_id) is not int or run_id <= 0 or type(pull_request) is not int or pull_request <= 0:
        raise ValueError("Documentation validation run and source PR are required")
    run = api(f"actions/runs/{run_id}")
    if (run.get("head_sha") != source or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or run.get("path", "").split("@", 1)[0] != ".github/workflows/docs-pages.yml"):
        raise ValueError("Exact approved source has not passed its documentation workflow")
    if docs_tree(source, api) != expected_tree:
        raise ValueError("Approved documentation tree no longer matches configuration")
    main = api("branches/main")["commit"]["sha"]
    # A normal merge makes the approved source an ancestor of main.
    if api(f"compare/{source}...{main}")["status"] in ("ahead", "identical"):
        return main, "main contains the approved source"
    # A squash merge changes ancestry. Recognize the source PR's exact docs tree
    # at its merge commit, then require that merge to remain in main's history.
    pr = api(f"pulls/{pull_request}")
    merged = pr.get("merge_commit_sha")
    if (pr.get("merged") is True and isinstance(merged, str)
            and re.fullmatch(r"[0-9a-f]{40}", merged)
            and docs_tree(merged, api) == expected_tree
            and api(f"compare/{merged}...{main}")["status"] in ("ahead", "identical")):
        return main, "main contains the source PR's approved documentation"
    return source, "approved documentation remains pinned until main catches up"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    source, reason = resolve(json.loads(args.config.read_text()))
    print("source_sha=" + source)
    print("selection_reason=" + reason)


if __name__ == "__main__":
    main()
