# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# License: Creative Commons NC BY SA 4.0
import asyncio
import tempfile
import unittest
from pathlib import Path

from openoptics.dashboard.broker import EventBroker
from openoptics.dashboard.collectors.reconfig_events import (
    METRIC_TYPE,
    ReconfigEventPublisher,
)
from openoptics.dashboard.events import MetricSample
from openoptics.dashboard.storage.repository import Repository


class TestReconfigEventPublisher(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self._tmp.name) / "db.sqlite3")
        self.broker = EventBroker()
        self.epoch = self.repo.create_epoch("test")
        self.pub = ReconfigEventPublisher()
        self.pub.bind(self.repo, self.broker, self.epoch.id)

    def tearDown(self):
        self.repo.close()
        self._tmp.cleanup()

    def test_emit_persists_sample(self):
        self.pub.emit("tor0", 3)
        rows = self.repo.query_samples(self.epoch.id, metric_type=METRIC_TYPE)
        self.assertEqual(len(rows), 1)
        (row,) = rows
        self.assertEqual(row.device, "tor0")
        self.assertEqual(row.value, 3.0)
        self.assertEqual(row.labels, {})
        self.assertEqual(row.epoch_id, self.epoch.id)

    def test_emit_assigns_monotonic_timesteps(self):
        for qid in (3, 5, 1, 9):
            self.pub.emit("tor0", qid)
        rows = self.repo.query_samples(self.epoch.id, metric_type=METRIC_TYPE)
        self.assertEqual([r.timestep for r in rows], [0, 1, 2, 3])

    def test_emit_unbound_is_noop(self):
        unbound = ReconfigEventPublisher()
        unbound.emit("tor0", 1)  # must not raise
        # Nothing persisted (no repo) and nothing to assert besides absence of errors.

    def test_emit_broadcasts_to_live_subscriber(self):
        async def scenario():
            broker = EventBroker()
            broker.bind_loop(asyncio.get_event_loop())
            repo = Repository(Path(self._tmp.name) / "live.sqlite3")
            epoch = repo.create_epoch("live")
            pub = ReconfigEventPublisher()
            pub.bind(repo, broker, epoch.id)
            try:
                with broker.subscribe() as q:
                    pub.emit("tor1", 7)
                    sample = await asyncio.wait_for(q.get(), timeout=1.0)
                self.assertIsInstance(sample, MetricSample)
                self.assertEqual(sample.metric_type, METRIC_TYPE)
                self.assertEqual(sample.device, "tor1")
                self.assertEqual(sample.value, 7.0)
            finally:
                repo.close()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
