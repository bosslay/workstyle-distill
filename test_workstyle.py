import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import workstyle


def candidate(**changes):
    rule = dict(id="preview", kind="preference", scope="ui-design", text="先选设计稿，再实现。",
                evidence=[dict(author="user", direct=True, source="message-1")])
    rule.update(changes)
    return dict(rules=[rule])


def snapshot(**changes):
    value = dict(complete=True, online=True, new_input=False, self_id="self",
                 observed_at=datetime.now(timezone.utc).isoformat(),
                 threads=[dict(id="self", status="active"), dict(id="peer", status="idle")])
    value.update(changes)
    return value


class WorkstyleTests(unittest.TestCase):
    def test_only_direct_or_independently_repeated_user_preferences_qualify(self):
        workstyle.validate(candidate())
        for change in [dict(kind="business_fact"), dict(kind="temporary"),
                       dict(evidence=[dict(author="document", direct=True, source="file-1")]),
                       dict(evidence=[dict(author="assistant", direct=True, source="reply-1")]),
                       dict(evidence=[dict(author="user", direct=False, source="same")]*2)]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                workstyle.validate(candidate(**change))

    def test_conflict_does_not_replace_another_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = workstyle.apply(root, candidate(), expected_revision=0)
            self.assertEqual(first["revision"], 1)
            with self.assertRaises(ValueError):
                workstyle.apply(root, candidate(scope="communication", supersedes="preview"), expected_revision=1)
            self.assertEqual(workstyle.read(root), first)

    def test_idempotence_and_revision_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = workstyle.apply(root, candidate(), expected_revision=0)
            self.assertEqual(workstyle.apply(root, candidate(), expected_revision=1), first)
            with self.assertRaises(ValueError):
                workstyle.apply(root, candidate(text="changed"), expected_revision=0)
            self.assertEqual(workstyle.read(root), first)

    def test_background_requires_fresh_complete_idle_evidence(self):
        self.assertTrue(workstyle.idle(snapshot()))
        cases = [snapshot(online=False), snapshot(complete=False), snapshot(new_input=True),
                 snapshot(observed_at="2020-01-01T00:00:00+00:00"),
                 snapshot(threads=[dict(id="self", status="active"), dict(id="peer", status="active")]),
                 snapshot(threads=[dict(id="peer", status="active")]),
                 snapshot(threads=[dict(id="peer", status="unknown")]),
                 snapshot(threads=[]), snapshot(threads=[dict(id="peer", status="idle")]),
                 snapshot(self_id=None)]
        for value in cases:
            self.assertFalse(workstyle.idle(value))
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                workstyle.apply(Path(folder), candidate(), expected_revision=0, mode="background")
            self.assertFalse((Path(folder)/"profile.json").exists())

    def test_locks_and_background_cooldown_prevent_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"update.lock").write_text("other writer", encoding="utf-8")
            with self.assertRaises(ValueError):
                workstyle.apply(root, candidate(), expected_revision=0)
            (root/"update.lock").unlink()
            first = workstyle.apply(root, candidate(), expected_revision=0, mode="background", gate=snapshot())
            with self.assertRaises(ValueError):
                workstyle.apply(root, candidate(id="new"), expected_revision=1, mode="background", gate=snapshot())
            self.assertEqual(workstyle.read(root), first)

    def test_public_scan_blocks_private_files_and_secrets_without_echoing_values(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"SKILL.md").write_text("Safe public instructions", encoding="utf-8")
            self.assertEqual(workstyle.public_findings(root), [])
            (root/"profile.json").write_text(json.dumps(candidate()), encoding="utf-8")
            address = "http://" + ".".join(map(str, [10, 24, 8, 2])) + "/api"
            sample_value = "credential" + "=" + "secret-value"
            (root/"SKILL.md").write_text(address + "\n" + sample_value, encoding="utf-8")
            findings = workstyle.public_findings(root)
            self.assertTrue(findings)
            self.assertNotIn("secret-value", str(findings))
            self.assertNotIn("10.24.8.2", str(findings))


if __name__ == "__main__":
    unittest.main()
