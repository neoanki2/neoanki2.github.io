#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("resolver", Path(__file__).with_name("resolve-docs-source.py"))
resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)


class DocumentationSourceTests(unittest.TestCase):
    def setUp(self):
        self.source, self.main, self.docs, self.merge = (digit * 40 for digit in "1234")
        self.config = {"schema_version": 1, "repository": resolver.SOURCE_REPOSITORY,
                       "source_sha": self.source, "docs_tree_sha": self.docs,
                       "documentation_run_id": 7, "source_pull_request": 88}
        self.run = {"head_sha": self.source, "status": "completed", "conclusion": "success",
                    "path": ".github/workflows/docs-pages.yml"}
        self.direct_status = "behind"
        self.pr = {"merged": False}
        self.merge_docs = self.docs

    def api(self, path):
        if path == "actions/runs/7": return self.run
        if path == "branches/main": return {"commit": {"sha": self.main}}
        if path == "pulls/88": return self.pr
        if path == f"git/commits/{self.source}": return {"tree": {"sha": "source-tree"}}
        if path == f"git/commits/{self.merge}": return {"tree": {"sha": "merge-tree"}}
        if path == "git/trees/source-tree": return {"tree": [{"path": "docs", "type": "tree", "sha": self.docs}]}
        if path == "git/trees/merge-tree": return {"tree": [{"path": "docs", "type": "tree", "sha": self.merge_docs}]}
        if path == f"compare/{self.source}...{self.main}": return {"status": self.direct_status}
        if path == f"compare/{self.merge}...{self.main}": return {"status": "ahead"}
        raise AssertionError("Unexpected GitHub request: " + path)

    def test_unmerged_documentation_remains_pinned(self):
        self.assertEqual(resolver.resolve(self.config, self.api)[0], self.source)

    def test_main_including_source_advances_normally(self):
        self.direct_status = "ahead"
        self.assertEqual(resolver.resolve(self.config, self.api)[0], self.main)

    def test_squash_merge_recognition_survives_later_main_changes(self):
        self.pr = {"merged": True, "merge_commit_sha": self.merge}
        self.assertEqual(resolver.resolve(self.config, self.api)[0], self.main)

    def test_squash_merge_with_different_docs_does_not_unpin(self):
        self.pr = {"merged": True, "merge_commit_sha": self.merge}
        self.merge_docs = "5" * 40
        self.assertEqual(resolver.resolve(self.config, self.api)[0], self.source)

    def test_failed_or_wrong_revision_validation_cannot_publish(self):
        for field, value in [("conclusion", "failure"), ("head_sha", self.main),
                             ("path", ".github/workflows/test.yml")]:
            with self.subTest(field=field):
                original = self.run[field]
                self.run[field] = value
                with self.assertRaises(ValueError): resolver.resolve(self.config, self.api)
                self.run[field] = original

    def test_wrong_repository_or_documentation_tree_cannot_publish(self):
        for field, value in [("repository", "other/repo"), ("docs_tree_sha", "6" * 40)]:
            with self.subTest(field=field):
                config = self.config | {field: value}
                with self.assertRaises(ValueError): resolver.resolve(config, self.api)


if __name__ == "__main__":
    unittest.main()
