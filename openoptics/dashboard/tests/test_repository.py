# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# License: Creative Commons NC BY SA 4.0
import tempfile
import time
import unittest
from pathlib import Path

from openoptics.dashboard.events import MetricSample
from openoptics.dashboard.storage.repository import Repository


class TestRepository(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self._tmpdir.name) / "test.sqlite3")

    def tearDown(self):
        self.repo.close()
        self._tmpdir.cleanup()

    def test_init_seeds_builtin_metric_types(self):
        types = {m.metric_type for m in self.repo.list_metric_types()}
        self.assertIn("queue_depth", types)
        self.assertIn("drop_count", types)

    def test_metric_types_listed_by_sort_order(self):
        ordered = [m.metric_type for m in self.repo.list_metric_types()]
        self.assertLess(
            ordered.index("queue_depth"), ordered.index("drop_count"),
            "queue_depth should come before drop_count per its sort_order",
        )

    def test_custom_metric_type_sort_order(self):
        # A type with a low sort_order should come before the built-ins.
        self.repo.upsert_metric_type(
            "top_priority", display_name="Top", unit=None, chart_kind="line",
            sort_order=1,
        )
        ordered = [m.metric_type for m in self.repo.list_metric_types()]
        self.assertEqual(ordered[0], "top_priority")

    def test_epoch_naming_appends_suffix_on_collision(self):
        self.repo.create_epoch("21-04-2026")
        self.assertEqual(
            self.repo.next_epoch_display_name("21-04-2026"), "21-04-2026 (1)"
        )
        self.repo.create_epoch("21-04-2026 (1)")
        self.assertEqual(
            self.repo.next_epoch_display_name("21-04-2026"), "21-04-2026 (2)"
        )

    def test_epoch_naming_is_stable_across_unique_seeds(self):
        self.assertEqual(self.repo.next_epoch_display_name("fresh"), "fresh")

    def test_insert_and_query_samples_round_trip(self):
        epoch = self.repo.create_epoch("ep1")
        samples = [
            MetricSample(
                metric_type="queue_depth",
                device="tor0",
                value=float(i),
                timestep=i,
                timestamp=time.time(),
                epoch_id=epoch.id,
                labels={"port": 0, "queue": i},
            )
            for i in range(3)
        ]
        self.repo.insert_samples(samples)

        out = self.repo.query_samples(epoch.id)
        self.assertEqual([s.timestep for s in out], [0, 1, 2])
        self.assertEqual(out[0].labels, {"port": 0, "queue": 0})

    def test_query_samples_filters(self):
        epoch = self.repo.create_epoch("ep2")
        now = time.time()
        self.repo.insert_samples([
            MetricSample("queue_depth", "tor0", 1, 0, now, epoch.id, {}),
            MetricSample("drop_count", "tor0", 5, 0, now, epoch.id, {}),
            MetricSample("queue_depth", "tor1", 2, 0, now, epoch.id, {}),
        ])
        depth_only = self.repo.query_samples(epoch.id, metric_type="queue_depth")
        self.assertEqual({s.device for s in depth_only}, {"tor0", "tor1"})
        tor0_only = self.repo.query_samples(epoch.id, device="tor0")
        self.assertEqual({s.metric_type for s in tor0_only}, {"queue_depth", "drop_count"})

    def test_distinct_devices(self):
        epoch = self.repo.create_epoch("ep3")
        now = time.time()
        self.repo.insert_samples([
            MetricSample("queue_depth", "tor0", 1, 0, now, epoch.id, {}),
            MetricSample("queue_depth", "tor1", 1, 0, now, epoch.id, {}),
            MetricSample("queue_depth", "tor0", 1, 1, now, epoch.id, {}),
        ])
        self.assertEqual(self.repo.distinct_devices(epoch.id), ["tor0", "tor1"])

    def test_topo_url_update(self):
        epoch = self.repo.create_epoch("ep4")
        self.assertIsNone(epoch.topo_image_url)
        self.repo.set_epoch_topo_url(epoch.id, "/media/topos/a.png")
        fetched = self.repo.get_epoch(epoch.id)
        self.assertEqual(fetched.topo_image_url, "/media/topos/a.png")

    def test_list_epochs_older_than(self):
        import time as _t
        e1 = self.repo.create_epoch("old")
        _t.sleep(0.01)
        cutoff = _t.time()
        _t.sleep(0.01)
        e2 = self.repo.create_epoch("new")

        old = self.repo.list_epochs_older_than(cutoff)
        self.assertEqual([e.id for e in old], [e1.id])

    def test_delete_epochs_cascades_samples(self):
        e1 = self.repo.create_epoch("ep1")
        e2 = self.repo.create_epoch("ep2")
        now = time.time()
        self.repo.insert_samples([
            MetricSample("queue_depth", "tor0", 1, 0, now, e1.id, {}),
            MetricSample("queue_depth", "tor0", 2, 1, now, e1.id, {}),
            MetricSample("queue_depth", "tor0", 3, 0, now, e2.id, {}),
        ])
        n = self.repo.delete_epochs([e1.id])
        self.assertEqual(n, 1)
        self.assertIsNone(self.repo.get_epoch(e1.id))
        self.assertEqual(len(self.repo.query_samples(e1.id)), 0)
        # e2 untouched
        self.assertEqual(len(self.repo.query_samples(e2.id)), 1)

    def test_delete_epochs_empty_list_is_noop(self):
        e = self.repo.create_epoch("ep")
        self.assertEqual(self.repo.delete_epochs([]), 0)
        self.assertIsNotNone(self.repo.get_epoch(e.id))

    def test_upsert_metric_type(self):
        self.repo.upsert_metric_type(
            "latency_ns", display_name="Latency", unit="ns", chart_kind="line"
        )
        types = {m.metric_type: m for m in self.repo.list_metric_types()}
        self.assertIn("latency_ns", types)
        self.assertEqual(types["latency_ns"].unit, "ns")

        # Upsert overwrites.
        self.repo.upsert_metric_type(
            "latency_ns", display_name="Hop Latency", unit="us", chart_kind="bar"
        )
        types = {m.metric_type: m for m in self.repo.list_metric_types()}
        self.assertEqual(types["latency_ns"].display_name, "Hop Latency")
        self.assertEqual(types["latency_ns"].chart_kind, "bar")


if __name__ == "__main__":
    unittest.main()
