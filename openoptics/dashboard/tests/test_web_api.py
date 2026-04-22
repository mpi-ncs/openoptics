# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# License: Creative Commons NC BY SA 4.0
import tempfile
import time
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient  # noqa: F401
    HAVE_FASTAPI = True
except Exception:
    HAVE_FASTAPI = False

from openoptics.dashboard.broker import EventBroker
from openoptics.dashboard.config import DashboardConfig
from openoptics.dashboard.events import MetricSample
from openoptics.dashboard.storage.repository import Repository


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed")
class TestWebAPI(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from openoptics.dashboard.web.app import create_app

        self._tmp = tempfile.TemporaryDirectory()
        state_dir = Path(self._tmp.name)
        self.config = DashboardConfig(state_dir=state_dir)
        self.config.ensure_dirs()

        self.repo = Repository(self.config.db_path)
        self.broker = EventBroker()

        # Seed one epoch with a few samples.
        self.epoch = self.repo.create_epoch("test-epoch")
        now = time.time()
        self.repo.insert_samples([
            MetricSample("queue_depth", "tor0", 1, 0, now, self.epoch.id, {"port": 0, "queue": 0}),
            MetricSample("queue_depth", "tor0", 2, 1, now, self.epoch.id, {"port": 0, "queue": 0}),
            MetricSample("drop_count", "network", 5, 0, now, self.epoch.id, {"switch": "tor0"}),
        ])

        self.app = create_app(self.config, self.repo, self.broker)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.repo.close()
        self._tmp.cleanup()

    def test_index_renders(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("OpenOptics Dashboard", r.text)

    def test_metric_types_lists_builtins(self):
        r = self.client.get("/api/metric_types")
        self.assertEqual(r.status_code, 200)
        types = {m["metric_type"] for m in r.json()}
        self.assertIn("queue_depth", types)
        self.assertIn("drop_count", types)

    def test_list_epochs(self):
        r = self.client.get("/api/epochs")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["display_name"], "test-epoch")

    def test_get_epoch_404(self):
        r = self.client.get("/api/epochs/99999")
        self.assertEqual(r.status_code, 404)

    def test_epoch_metrics_groups_by_type(self):
        r = self.client.get(f"/api/epochs/{self.epoch.id}/metrics")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("queue_depth", data)
        self.assertIn("drop_count", data)
        depth_series = data["queue_depth"]
        self.assertEqual(len(depth_series), 1)  # one (device, labels) group
        self.assertEqual(depth_series[0]["device"], "tor0")
        self.assertEqual(depth_series[0]["labels"], {"port": 0, "queue": 0})
        self.assertEqual(depth_series[0]["series"], [[0, 1.0], [1, 2.0]])

    def test_epoch_metrics_filters_by_type(self):
        r = self.client.get(
            f"/api/epochs/{self.epoch.id}/metrics",
            params={"metric_type": "drop_count"},
        )
        data = r.json()
        self.assertEqual(list(data.keys()), ["drop_count"])

    def test_websocket_receives_published_metric(self):
        with self.client.websocket_connect(
            f"/ws/live?epoch_id={self.epoch.id}"
        ) as ws:
            # Register the loop so publish_threadsafe has somewhere to go.
            import asyncio
            loop = self.app.state.broker._loop
            self.assertIsNotNone(loop, "broker must bind a loop in the app")

            sample = MetricSample(
                metric_type="queue_depth",
                device="tor0",
                value=42,
                timestep=99,
                timestamp=time.time(),
                epoch_id=self.epoch.id,
                labels={"port": 0, "queue": 0},
            )
            # The TestClient runs the app on the event loop thread-locally;
            # we can call publish() on it synchronously via the broker.
            asyncio.run_coroutine_threadsafe(self.broker.publish(sample), loop).result(timeout=1.0)
            msg = ws.receive_json()
            self.assertEqual(msg["kind"], "metric")
            self.assertEqual(msg["value"], 42)
            self.assertEqual(msg["timestep"], 99)


if __name__ == "__main__":
    unittest.main()
