# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# License: Creative Commons NC BY SA 4.0
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from openoptics._cli import clean_dashboard as cli
from openoptics.dashboard.config import DashboardConfig
from openoptics.dashboard.storage.repository import Repository


class TestParseDuration(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(cli.parse_duration("30s"), 30.0)
        self.assertEqual(cli.parse_duration("10m"), 600.0)
        self.assertEqual(cli.parse_duration("2h"), 7200.0)
        self.assertEqual(cli.parse_duration("7d"), 7 * 86400.0)
        self.assertEqual(cli.parse_duration("1.5h"), 5400.0)

    def test_invalid(self):
        import argparse
        for s in ("", "7", "7x", "abc", "d7"):
            with self.assertRaises(argparse.ArgumentTypeError):
                cli.parse_duration(s)


class TestCleanCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self._tmp.name)
        cfg = DashboardConfig(state_dir=self.state_dir)
        cfg.ensure_dirs()
        self.cfg = cfg
        self.repo = Repository(cfg.db_path)

        # Seed: 2 epochs, a few samples, matching PNGs on disk.
        old = self.repo.create_epoch("old")
        self.old_id = old.id
        time.sleep(0.01)
        self.cutoff = time.time()
        time.sleep(0.01)
        new = self.repo.create_epoch("new")
        self.new_id = new.id

        (cfg.topos_dir / f"epoch_{old.id}.png").write_bytes(b"\x89PNG\r\n" + b"a" * 64)
        (cfg.topos_dir / f"epoch_{new.id}.png").write_bytes(b"\x89PNG\r\n" + b"b" * 64)

    def tearDown(self):
        self.repo.close()
        self._tmp.cleanup()

    def _run(self, *args):
        with patch.dict("os.environ", {"OPENOPTICS_STATE_DIR": str(self.state_dir)}):
            return cli.main(list(args))

    def test_dry_run_wipe_all_changes_nothing(self):
        rc = self._run("--dry-run")
        self.assertEqual(rc, 0)
        self.assertTrue(self.cfg.db_path.exists())
        self.assertTrue((self.cfg.topos_dir / f"epoch_{self.old_id}.png").exists())

    def test_wipe_all_force_removes_everything(self):
        # Repository connection holds an FD; close before deleting the file
        # because that's also what a real user would do (script not running).
        self.repo.close()
        rc = self._run("--force")
        self.assertEqual(rc, 0)
        self.assertFalse(self.cfg.db_path.exists())
        self.assertFalse((self.cfg.topos_dir / f"epoch_{self.old_id}.png").exists())
        self.assertFalse((self.cfg.topos_dir / f"epoch_{self.new_id}.png").exists())
        # Reopen for tearDown's close() — no-op on a fresh repo.
        self.repo = Repository(self.cfg.db_path)

    def _run_with_fake_now(self, fake_now, *args):
        """Run the CLI with ``time.time()`` pinned to ``fake_now`` in the CLI module."""
        with patch.dict("os.environ", {"OPENOPTICS_STATE_DIR": str(self.state_dir)}):
            with patch("openoptics._cli.clean_dashboard.time.time",
                       return_value=fake_now):
                return cli.main(list(args))

    def test_older_than_selective_deletion(self):
        """Cutoff between the two epochs' timestamps → only the old one goes."""
        new_epoch = self.repo.get_epoch(self.new_id)
        self.repo.close()

        # Pin CLI's "now" so cutoff = fake_now - 0s = a point between the two
        # epochs. Deterministic regardless of test-runner timing.
        fake_now = new_epoch.created_at - 0.001
        rc = self._run_with_fake_now(fake_now, "--force", "--older-than", "0s")
        self.assertEqual(rc, 0)

        self.repo = Repository(self.cfg.db_path)
        remaining = {e.id for e in self.repo.list_epochs()}
        self.assertEqual(remaining, {self.new_id})
        self.assertFalse((self.cfg.topos_dir / f"epoch_{self.old_id}.png").exists())
        self.assertTrue((self.cfg.topos_dir / f"epoch_{self.new_id}.png").exists())

    def test_dry_run_older_than_preserves_matched_data(self):
        new_epoch = self.repo.get_epoch(self.new_id)
        self.repo.close()

        fake_now = new_epoch.created_at - 0.001
        rc = self._run_with_fake_now(fake_now, "--dry-run", "--older-than", "0s")
        self.assertEqual(rc, 0)

        self.repo = Repository(self.cfg.db_path)
        remaining = {e.id for e in self.repo.list_epochs()}
        self.assertEqual(remaining, {self.old_id, self.new_id})
        self.assertTrue((self.cfg.topos_dir / f"epoch_{self.old_id}.png").exists())

    def test_nothing_to_clean_empty_dir(self):
        self.repo.close()
        self.cfg.db_path.unlink()
        for p in list(self.cfg.topos_dir.iterdir()):
            p.unlink()
        rc = self._run("--force")
        self.assertEqual(rc, 0)
        self.repo = Repository(self.cfg.db_path)


if __name__ == "__main__":
    unittest.main()
