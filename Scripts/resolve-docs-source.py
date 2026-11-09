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


REQUIRED_DOCUMENTATION_JOBS = {
    "Documentation content validation", "API reference and contract",
    "Documentation and screenshot gate", "Build documentation site",
}


def resolve_dispatched(source, run_id, api=github):
    """A main-push build may publish after its content jobs, without a circular gate."""
    if not re.fullmatch(r"[0-9a-f]{40}", source) or not str(run_id).isdigit():
        raise ValueError("Dispatch requires an exact source SHA and documentation run ID")
    run = api(f"actions/runs/{run_id}")
    if (run.get("head_sha") != source or run.get("event") != "push"
            or run.get("head_branch") != "main"
            or run.get("repository", {}).get("full_name") != SOURCE_REPOSITORY
            or run.get("path", "").split("@", 1)[0] != ".github/workflows/docs-pages.yml"):
        raise ValueError("Dispatched source is not the trusted main documentation workflow")
    main = api("branches/main")["commit"]["sha"]
    if api(f"compare/{source}...{main}")["status"] not in ("ahead", "identical"):
        raise ValueError("Dispatched documentation source is not in main history")
    jobs = api(f"actions/runs/{run_id}/jobs?filter=latest&per_page=100")["jobs"]
    succeeded = {job["name"] for job in jobs if job.get("status") == "completed" and job.get("conclusion") == "success"}
    if not REQUIRED_DOCUMENTATION_JOBS <= succeeded:
        raise ValueError("Dispatched source has not passed every documentation content/build gate")
    return source, "exact main source passed independent documentation content and build jobs"


def latest_validated(api=github):
    runs = api("actions/workflows/docs-pages.yml/runs?branch=main&event=push&per_page=20")["workflow_runs"]
    for run in runs:
        try:
            return resolve_dispatched(run["head_sha"], run["id"], api)
        except ValueError:
            continue
    raise ValueError("No recent main documentation build has passed its content gates")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-sha")
    parser.add_argument("--documentation-run-id")
    args = parser.parse_args()
    if bool(args.source_sha) != bool(args.documentation_run_id):
        parser.error("source SHA and documentation run ID must be supplied together")
    if args.source_sha:
        source, reason = resolve_dispatched(args.source_sha, args.documentation_run_id)
    else:
        try:
            source, reason = latest_validated()
        except ValueError:
            source, reason = resolve(json.loads(args.config.read_text()))
    print("source_sha=" + source)
    print("selection_reason=" + reason)


if __name__ == "__main__":
    main()
