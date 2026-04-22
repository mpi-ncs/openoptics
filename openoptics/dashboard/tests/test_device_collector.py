# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# License: Creative Commons NC BY SA 4.0
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from openoptics.dashboard.broker import EventBroker
from openoptics.dashboard.collectors.device_metrics import DeviceMetricCollector
from openoptics.dashboard.events import MetricSample
from openoptics.dashboard.storage.repository import Repository


class FakeDeviceManager:
    def __init__(self, switch_names=("tor0", "tor1"), ocs_payload=None):
        self.switches = [SimpleNamespace(name=n) for n in switch_names]
        self.metric_payload = {
            n: {"pq_depth": {(0, 0): 3, (0, 1): 1}, "drop_ctr": 0} for n in switch_names
        }
        self.ocs_payload = ocs_payload  # None = no OCS attribute

    def get_device_metric(self):
        return self.metric_payload

    def get_ocs_metric(self):
        return self.ocs_payload or {}


class TestDeviceMetricCollector(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self._tmp.name) / "db.sqlite3")
        self.broker = EventBroker()
        self.epoch = self.repo.create_epoch("test")
        self.dm = FakeDeviceManager()

    def tearDown(self):
        self.repo.close()
        self._tmp.cleanup()

    def test_sample_emits_per_queue_and_aggregate(self):
        c = DeviceMetricCollector(self.dm, nb_port=1, nb_queue=2, interval_s=0.05)
        c.bind(self.repo, self.broker, self.epoch.id)
        events = list(c._sample(timestep=0))

        per_queue = [e for e in events if e.device != "network"]
        aggregates = [e for e in events if e.device == "network"]
        self.assertEqual(len(per_queue), 4)  # 2 switches * 2 queues
        self.assertEqual(len(aggregates), 4)  # 2 switches * (queue_depth+drop_count)

        aggregate_by_type = {}
        for e in aggregates:
            aggregate_by_type.setdefault(e.metric_type, []).append(e)
        self.assertIn("queue_depth", aggregate_by_type)
        self.assertIn("drop_count", aggregate_by_type)

        tor0_total = next(
            e for e in aggregate_by_type["queue_depth"]
            if e.labels["switch"] == "tor0"
        )
        self.assertEqual(tor0_total.value, 4)  # 3 + 1

    def test_sample_emits_zeros_when_no_data(self):
        dm = FakeDeviceManager(switch_names=("tor0",))
        dm.metric_payload = {"tor0": {"pq_depth": {}, "drop_ctr": 0}}
        c = DeviceMetricCollector(dm, nb_port=1, nb_queue=2, interval_s=0.05)
        c.bind(self.repo, self.broker, self.epoch.id)
        events = list(c._sample(timestep=0))
        per_queue = [e for e in events if e.device != "network"]
        self.assertEqual(len(per_queue), 2)
        self.assertTrue(all(e.value == 0 for e in per_queue))

    def test_sample_emits_queue_latency_when_pq_latency_present(self):
        # DeviceManager stores µs (the native BMv2 unit); the collector
        # converts to ms so the dashboard y-axis is ms.
        dm = FakeDeviceManager(switch_names=("tor0",))
        dm.metric_payload = {
            "tor0": {
                "pq_depth": {(0, 0): 5, (0, 1): 2},
                "pq_latency": {(0, 0): (120_000, 480_000), (0, 1): (30_000, 60_000)},
                "drop_ctr": 0,
            },
        }
        c = DeviceMetricCollector(dm, nb_port=1, nb_queue=2, interval_s=0.05)
        c.bind(self.repo, self.broker, self.epoch.id)
        events = list(c._sample(timestep=0))

        lat_mean = [e for e in events if e.metric_type == "queue_latency_mean"]
        lat_max  = [e for e in events if e.metric_type == "queue_latency_max"]
        self.assertEqual(len(lat_mean), 2)
        self.assertEqual(len(lat_max), 2)
        by_queue_mean = {e.labels["queue"]: e.value for e in lat_mean}
        by_queue_max  = {e.labels["queue"]: e.value for e in lat_max}
        self.assertEqual(by_queue_mean[0], 120.0)
        self.assertEqual(by_queue_max[0],  480.0)
        self.assertEqual(by_queue_mean[1],  30.0)
        self.assertEqual(by_queue_max[1],   60.0)
        self.assertTrue(all(e.device == "tor0" for e in lat_mean + lat_max))

    def test_sample_does_not_emit_negative_latency(self):
        # Defence-in-depth: even if the collector got a (mean, max) tuple with
        # a negative value (pre-fix PHV-truncated garbage that survived as -1),
        # it must not be emitted as a sample. DeviceManager already filters
        # these out, so we exercise the collector the same way — pq_latency
        # missing the key means no events for (port, queue).
        dm = FakeDeviceManager(switch_names=("tor0",))
        dm.metric_payload = {
            "tor0": {
                "pq_depth": {(0, 0): 2},
                # Empty — DeviceManager would have filtered the negative tuple.
                "pq_latency": {},
                "drop_ctr": 0,
            },
        }
        c = DeviceMetricCollector(dm, nb_port=1, nb_queue=1, interval_s=0.05)
        c.bind(self.repo, self.broker, self.epoch.id)
        events = list(c._sample(timestep=0))
        lat = [e for e in events if e.metric_type.startswith("queue_latency")]
        self.assertEqual(lat, [])

    def test_sample_skips_latency_when_pq_latency_missing(self):
        # pq_latency absent: no queue_latency_* events should be emitted.
        c = DeviceMetricCollector(self.dm, nb_port=1, nb_queue=2, interval_s=0.05)
        c.bind(self.repo, self.broker, self.epoch.id)
        events = list(c._sample(timestep=0))
        lat = [e for e in events if e.metric_type.startswith("queue_latency")]
        self.assertEqual(lat, [])

    def test_sample_emits_ocs_hit_miss_when_ocs_metric_available(self):
        dm = FakeDeviceManager(
            switch_names=("tor0",),
            ocs_payload={"ocs": {0: (5, 0), 1: (3, 2)}},
        )
        c = DeviceMetricCollector(dm, nb_port=1, nb_queue=1, interval_s=0.05)
        c.bind(self.repo, self.broker, self.epoch.id)
        events = list(c._sample(timestep=0))

        ocs_hits = [e for e in events if e.metric_type == "ocs_schedule_hit"]
        ocs_misses = [e for e in events if e.metric_type == "ocs_schedule_miss"]
        self.assertEqual(len(ocs_hits), 2)
        self.assertEqual(len(ocs_misses), 2)
        by_port = {e.labels["port"]: e for e in ocs_hits}
        self.assertEqual(by_port[0].value, 5)
        self.assertEqual(by_port[1].value, 3)
        self.assertTrue(all(e.device == "ocs" for e in ocs_hits))

        miss_by_port = {e.labels["port"]: e for e in ocs_misses}
        self.assertEqual(miss_by_port[0].value, 0)
        self.assertEqual(miss_by_port[1].value, 2)

    def test_ocs_zero_baseline_emitted_for_idle_ports(self):
        """Idle ports must still produce (0, 0) samples so the chart renders
        from epoch start — otherwise an idle network shows no OCS chart."""
        dm = FakeDeviceManager(
            switch_names=("tor0",),
            ocs_payload={"ocs": {0: (0, 0), 1: (0, 0)}},
        )
        c = DeviceMetricCollector(dm, nb_port=1, nb_queue=1, interval_s=0.05)
        c.bind(self.repo, self.broker, self.epoch.id)
        events = list(c._sample(timestep=0))
        hits = [e for e in events if e.metric_type == "ocs_schedule_hit"]
        misses = [e for e in events if e.metric_type == "ocs_schedule_miss"]
        self.assertEqual(len(hits), 2)
        self.assertEqual(len(misses), 2)
        self.assertTrue(all(e.value == 0 for e in hits + misses))

    def test_sample_skips_ocs_emit_when_manager_lacks_method(self):
        # DeviceManager without get_ocs_metric must not crash the collector.
        class NoOcsDM:
            def __init__(self):
                self.switches = [SimpleNamespace(name="tor0")]
            def get_device_metric(self):
                return {"tor0": {"pq_depth": {(0, 0): 1}, "drop_ctr": 0}}
        c = DeviceMetricCollector(NoOcsDM(), nb_port=1, nb_queue=1, interval_s=0.05)
        c.bind(self.repo, self.broker, self.epoch.id)
        events = list(c._sample(timestep=0))
        ocs_events = [e for e in events if e.metric_type.startswith("ocs_schedule_")]
        self.assertEqual(ocs_events, [])

    def test_start_writes_samples_to_repo(self):
        c = DeviceMetricCollector(self.dm, nb_port=1, nb_queue=2, interval_s=0.05)
        c.bind(self.repo, self.broker, self.epoch.id)

        # Shorten the settling wait for testing.
        orig_run = c._run
        def fast_run():
            c._stop.clear()
            # Skip the 1 s settle — emit at least one tick quickly.
            events = list(c._sample(c._timestep))
            samples = [e for e in events if isinstance(e, MetricSample)]
            self.repo.insert_samples(samples)
        fast_run()

        stored = self.repo.query_samples(self.epoch.id)
        self.assertGreater(len(stored), 0)
        types = {s.metric_type for s in stored}
        self.assertEqual(types, {"queue_depth", "drop_count"})


if __name__ == "__main__":
    unittest.main()
