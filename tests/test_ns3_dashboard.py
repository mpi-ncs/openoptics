# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# License: Creative Commons NC BY SA 4.0
#
# Tests for M4 dashboard integration: Ns3MetricSink + Ns3Backend wiring
# + end-to-end SQLite population during a simulation run.

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.ns3_helpers import skip_if_no_ns3, ns3_available

# A range of ports starting well above the default (8001) so tests don't
# collide with a user's live dashboard. Each test uses port = BASE + index.
_PORT_BASE = 18400


class Ns3MetricSinkPureUnitTests(unittest.TestCase):
    """Pure-Python unit tests for the sink — no ns-3 required."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "dashboard.sqlite3"

    def _make_repo(self):
        from openoptics.dashboard.storage.repository import Repository
        return Repository(self.db_path)

    def test_sink_before_bind_is_safe(self):
        """Calling on_*_snapshot on an unbound sink is a no-op, not a crash."""
        from openoptics.dashboard.collectors.ns3_metrics import Ns3MetricSink
        sink = Ns3MetricSink()
        # Would AttributeError on the repo if not guarded.
        sink.on_ocs_snapshot(1_000_000, 10, 0)
        sink.on_tor_snapshot(
            1_000_000, 0, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1, 0,
        )

    def test_sink_registers_custom_metric_types(self):
        """bind() should upsert the ns-3-specific metric_type rows."""
        from openoptics.dashboard.broker import EventBroker
        from openoptics.dashboard.collectors.ns3_metrics import Ns3MetricSink
        repo = self._make_repo()
        try:
            epoch = repo.create_epoch("test")
            sink = Ns3MetricSink()
            sink.bind(repo, EventBroker(queue_size=4), epoch.id)
            metas = {m.metric_type: m for m in repo.list_metric_types()}
            for expected in ("ocs_forward", "tor_forwarded",
                             "tor_delivered", "queue_peak",
                             "queue_bytes", "queue_peak_bytes",
                             "tor_overflow_drops"):
                self.assertIn(expected, metas, f"missing {expected}")
        finally:
            repo.close()

    def test_sink_emits_expected_rows_for_ocs(self):
        from openoptics.dashboard.broker import EventBroker
        from openoptics.dashboard.collectors.ns3_metrics import Ns3MetricSink
        repo = self._make_repo()
        try:
            epoch = repo.create_epoch("test")
            sink = Ns3MetricSink()
            sink.bind(repo, EventBroker(queue_size=4), epoch.id)
            sink.on_ocs_snapshot(500_000, 42, 3)

            rows = sqlite3.connect(self.db_path).execute(
                "SELECT metric_type, device, value, timestep FROM metric_samples "
                "ORDER BY metric_type"
            ).fetchall()
            expected = {
                ("drop_count", "ocs", 3.0, 500),
                ("ocs_forward", "ocs", 42.0, 500),
            }
            self.assertEqual(set(rows), expected)
        finally:
            repo.close()

    def test_sink_emits_expected_rows_for_tor(self):
        from openoptics.dashboard.broker import EventBroker
        from openoptics.dashboard.collectors.ns3_metrics import Ns3MetricSink
        repo = self._make_repo()
        try:
            epoch = repo.create_epoch("test")
            sink = Ns3MetricSink()
            sink.bind(repo, EventBroker(queue_size=4), epoch.id)
            # Snapshot for tor 2: fwd=10, delivered=7, drops=1, depth=5,
            # peak=3, bytes=5000, peak_bytes=6000, cq_drops=0,
            # ingress_host=20, ingress_uplink=17, overflow_drops=4.
            sink.on_tor_snapshot(
                2_000_000, 2, 10, 7, 1, 5, 3, 5000, 6000, 0, 20, 17, 4,
            )
            rows = sqlite3.connect(self.db_path).execute(
                "SELECT metric_type, device, value, timestep FROM metric_samples "
                "ORDER BY metric_type"
            ).fetchall()
            self.assertEqual(
                set(rows),
                {
                    ("drop_count",         "tor2", 1.0, 2000),
                    ("queue_bytes",        "tor2", 5000.0, 2000),
                    ("queue_depth",        "tor2", 5.0, 2000),
                    ("queue_peak_bytes",   "tor2", 6000.0, 2000),
                    ("queue_peak",         "tor2", 3.0, 2000),
                    ("tor_delivered",      "tor2", 7.0, 2000),
                    ("tor_forwarded",      "tor2", 10.0, 2000),
                    ("tor_overflow_drops", "tor2", 4.0, 2000),
                },
            )
        finally:
            repo.close()


def _env_override(**kv):
    """Context manager that sets env vars and restores them after."""
    class _Ctx:
        def __enter__(self):
            self._saved = {k: os.environ.get(k) for k in kv}
            os.environ.update({k: str(v) for k, v in kv.items()})
        def __exit__(self, *a):
            for k, v in self._saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return _Ctx()


@skip_if_no_ns3
class Ns3DashboardEndToEndTests(unittest.TestCase):
    """Drive a real Ns3Backend with use_webserver=True; inspect SQLite."""

    def setUp(self):
        # Prevent run() from blocking on input().
        os.environ["OPENOPTICS_NS3_NO_PAUSE"] = "1"
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._state_dir = Path(self._tmp.name)

    def tearDown(self):
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    def _state_env(self, port):
        return _env_override(
            OPENOPTICS_STATE_DIR=str(self._state_dir),
            OPENOPTICS_DASHBOARD_PORT=str(port),
        )

    def test_dashboard_starts_for_ns3_backend(self):
        """use_webserver=True creates a real DashboardService for ns-3."""
        from openoptics import OpticalTopo, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend
        from openoptics.dashboard.service import DashboardService

        backend = Ns3Backend()
        with self._state_env(_PORT_BASE + 1):
            with patch("openoptics.Toolbox.create_backend", return_value=backend):
                net = Toolbox.BaseNetwork(
                    name="dash_starts", backend="ns3", nb_node=4,
                    time_slice_duration_us=10_000, guardband_ms=0,
                    use_webserver=True, simulation_stop_s=0.1,
                )
                net.deploy_topo(OpticalTopo.round_robin(nb_node=4))
                net.start_monitor()

            self.assertIsInstance(net.dashboard, DashboardService)
            self.assertTrue(backend._dashboard_attached)
            self.assertIsNotNone(backend._sink)
            net.stop_network()

    def test_snapshot_events_reach_sqlite(self):
        """After Simulator::Run(), SQLite has samples for the expected types."""
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        backend = Ns3Backend()
        with self._state_env(_PORT_BASE + 2):
            with patch("openoptics.Toolbox.create_backend", return_value=backend):
                net = Toolbox.BaseNetwork(
                    name="e2e_sqlite", backend="ns3", nb_node=4,
                    time_slice_duration_us=10_000, guardband_ms=0,
                    use_webserver=True, simulation_stop_s=0.3,
                )
                net.deploy_topo(OpticalTopo.round_robin(nb_node=4))
                net.deploy_routing(
                    OpticalRouting.routing_direct(net.get_topo()),
                    routing_mode="Per-hop",
                )
                net.udp_traffic().echo(
                    0, 1, start_s=0.01, stop_s=0.25,
                    num_packets=10, interval_s=0.02,
                ).install()
                net.start()

            db_path = net.dashboard.config.db_path
            conn = sqlite3.connect(db_path)
            types_present = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT metric_type FROM metric_samples"
                )
            }
            # ns-3 metric kinds must have at least one row.
            for mt in ("drop_count", "queue_depth", "queue_peak",
                       "queue_bytes", "queue_peak_bytes",
                       "ocs_forward", "tor_forwarded", "tor_delivered"):
                self.assertIn(mt, types_present,
                              f"expected {mt} in SQLite, got {types_present}")

            # Every ToR + OCS must have at least one row for its primary
            # counters. (With 4 ToRs + 1 OCS + 5 metric types, we get at
            # minimum 4*3 + 2 = 14 distinct (metric_type, device) pairs.)
            pairs = {
                (row[0], row[1])
                for row in conn.execute(
                    "SELECT DISTINCT metric_type, device FROM metric_samples"
                )
            }
            self.assertGreaterEqual(len(pairs), 14)

            # Final tor_forwarded value for tor0 should match the counter.
            (max_fwd,) = conn.execute(
                "SELECT MAX(value) FROM metric_samples "
                "WHERE metric_type = 'tor_forwarded' AND device = 'tor0'"
            ).fetchone()
            self.assertEqual(int(max_fwd), backend._tor_apps[0].GetForwardedCount())

    def test_snapshot_cadence_matches_slice_duration(self):
        """One snapshot per slice (default) → ≥ N_slices distinct timesteps."""
        from openoptics import OpticalTopo, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        slice_us = 10_000       # 10 ms / slice
        sim_s = 0.3             # → ≥ 30 snapshots for the OCS
        backend = Ns3Backend()
        with self._state_env(_PORT_BASE + 3):
            with patch("openoptics.Toolbox.create_backend", return_value=backend):
                net = Toolbox.BaseNetwork(
                    name="cadence", backend="ns3", nb_node=4,
                    time_slice_duration_us=slice_us, guardband_ms=0,
                    use_webserver=True, simulation_stop_s=sim_s,
                )
                net.deploy_topo(OpticalTopo.round_robin(nb_node=4))
                net.start()

            conn = sqlite3.connect(net.dashboard.config.db_path)
            (n_ts,) = conn.execute(
                "SELECT COUNT(DISTINCT timestep) FROM metric_samples "
                "WHERE metric_type = 'ocs_forward' AND device = 'ocs'"
            ).fetchone()
            # Allow tiny slop: sim stops just short of exactly N_slices.
            expected_min = int(sim_s * 1_000_000 / slice_us) - 1
            self.assertGreaterEqual(
                n_ts, expected_min,
                f"expected ≥ {expected_min} ocs snapshots, got {n_ts}",
            )

    def test_snapshot_interval_override(self):
        """snapshot_interval_us kwarg changes cadence without touching slice."""
        from openoptics import OpticalTopo, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        slice_us = 10_000
        # Sample 3x faster than the slice clock.
        sample_us = 3_000
        backend = Ns3Backend()
        with self._state_env(_PORT_BASE + 4):
            with patch("openoptics.Toolbox.create_backend", return_value=backend):
                net = Toolbox.BaseNetwork(
                    name="override", backend="ns3", nb_node=4,
                    time_slice_duration_us=slice_us, guardband_ms=0,
                    snapshot_interval_us=sample_us,
                    use_webserver=True, simulation_stop_s=0.1,
                )
                net.deploy_topo(OpticalTopo.round_robin(nb_node=4))
                net.start()

            self.assertEqual(backend._snapshot_interval_us, sample_us)

            conn = sqlite3.connect(net.dashboard.config.db_path)
            (n_ts,) = conn.execute(
                "SELECT COUNT(DISTINCT timestep) FROM metric_samples "
                "WHERE device = 'ocs'"
            ).fetchone()
            # 100ms / 3ms ≈ 33 ticks; allow slop.
            self.assertGreaterEqual(n_ts, 25)

    def test_phase_shifted_workload_records_queue_depth(self):
        """Sub-slice snapshots catch packets waiting for a future slice."""
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        backend = Ns3Backend()
        with self._state_env(_PORT_BASE + 5):
            with patch("openoptics.Toolbox.create_backend", return_value=backend):
                net = Toolbox.BaseNetwork(
                    name="queue_visible", backend="ns3", nb_node=4,
                    time_slice_duration_us=10_000, guardband_ms=0,
                    snapshot_interval_us=1_000,
                    use_webserver=True, simulation_stop_s=0.2,
                )
                net.deploy_topo(OpticalTopo.round_robin(nb_node=4))
                net.deploy_routing(
                    OpticalRouting.routing_direct(net.get_topo()),
                    routing_mode="Per-hop",
                )
                backend.udp_traffic().echo(
                    0, 1, start_s=0.045, stop_s=0.12,
                    num_packets=40, interval_s=0.001,
                ).install()
                net.start()

            conn = sqlite3.connect(net.dashboard.config.db_path)
            (max_depth,) = conn.execute(
                "SELECT MAX(value) FROM metric_samples "
                "WHERE metric_type = 'queue_depth' AND device = 'tor0'"
            ).fetchone()
            (max_peak,) = conn.execute(
                "SELECT MAX(value) FROM metric_samples "
                "WHERE metric_type = 'queue_peak' AND device = 'tor0'"
            ).fetchone()
            self.assertGreaterEqual(max_depth, 5.0)
            self.assertGreaterEqual(max_peak, 5.0)
            self.assertEqual(backend._tor_apps[0].GetDropCount(), 0)
            self.assertEqual(backend._tor_apps[0].GetSliceOverflowDrops(), 0)

    def test_source_routed_workload_records_queue_depth(self):
        """Source-routed direct traffic exposes the same queued slice wait."""
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        backend = Ns3Backend()
        with self._state_env(_PORT_BASE + 6):
            with patch("openoptics.Toolbox.create_backend", return_value=backend):
                net = Toolbox.BaseNetwork(
                    name="source_queue_visible", backend="ns3", nb_node=4,
                    time_slice_duration_us=10_000, guardband_ms=0,
                    snapshot_interval_us=1_000,
                    use_webserver=True, simulation_stop_s=0.2,
                )
                net.deploy_topo(OpticalTopo.round_robin(nb_node=4))
                net.deploy_routing(
                    OpticalRouting.routing_direct(net.get_topo()),
                    routing_mode="Source",
                )
                backend.udp_traffic().echo(
                    0, 1, start_s=0.045, stop_s=0.12,
                    num_packets=40, interval_s=0.001,
                ).install()
                net.start()

            conn = sqlite3.connect(net.dashboard.config.db_path)
            (max_depth,) = conn.execute(
                "SELECT MAX(value) FROM metric_samples "
                "WHERE metric_type = 'queue_depth' AND device = 'tor0'"
            ).fetchone()
            (max_peak,) = conn.execute(
                "SELECT MAX(value) FROM metric_samples "
                "WHERE metric_type = 'queue_peak' AND device = 'tor0'"
            ).fetchone()
            self.assertGreaterEqual(max_depth, 5.0)
            self.assertGreaterEqual(max_peak, 5.0)
            self.assertEqual(backend._tor_apps[0].GetDropCount(), 0)
            self.assertEqual(backend._tor_apps[0].GetSliceOverflowDrops(), 0)
            self.assertEqual(backend._tor_apps[0].GetPerHopEntryCount(), 0)

    def test_tcp_bulk_workload_records_queue_depth(self):
        """TCP bulk traffic also produces visible queued slice occupancy."""
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        backend = Ns3Backend()
        with self._state_env(_PORT_BASE + 7):
            with patch("openoptics.Toolbox.create_backend", return_value=backend):
                net = Toolbox.BaseNetwork(
                    name="tcp_queue_visible", backend="ns3", nb_node=4,
                    time_slice_duration_us=10_000, guardband_ms=0,
                    snapshot_interval_us=1_000,
                    ocs_tor_link_bw_gbps=100,
                    tor_host_link_bw_gbps=1,
                    use_webserver=True, simulation_stop_s=0.25,
                )
                net.deploy_topo(OpticalTopo.round_robin(nb_node=4))
                net.deploy_routing(
                    OpticalRouting.routing_direct(net.get_topo()),
                    routing_mode="Per-hop",
                )
                backend.tcp_traffic().bulk(
                    0, 1, size_bytes=2_000_000, chunk_size_bytes=1448,
                    start_s=0.052, stop_s=0.18,
                ).install()
                net.start()

            conn = sqlite3.connect(net.dashboard.config.db_path)
            (max_depth,) = conn.execute(
                "SELECT MAX(value) FROM metric_samples "
                "WHERE metric_type = 'queue_depth' AND device = 'tor0'"
            ).fetchone()
            (max_peak,) = conn.execute(
                "SELECT MAX(value) FROM metric_samples "
                "WHERE metric_type = 'queue_peak' AND device = 'tor0'"
            ).fetchone()
            self.assertGreaterEqual(max_depth, 20.0)
            self.assertGreaterEqual(max_peak, 20.0)
            self.assertGreater(backend._tor_apps[0].GetForwardedCount(), 0)
            self.assertEqual(backend._tor_apps[0].GetDropCount(), 0)
            self.assertEqual(backend._tor_apps[0].GetSliceOverflowDrops(), 0)

    def test_no_dashboard_when_use_webserver_false(self):
        """ns-3 backend with use_webserver=False: no sink, no pause, M1 behaviour."""
        from openoptics import OpticalTopo, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend
        from openoptics.dashboard.service import NullDashboard

        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="no_dash", backend="ns3", nb_node=4,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False, simulation_stop_s=0.1,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=4))
            net.start()

        self.assertIsInstance(net.dashboard, NullDashboard)
        self.assertFalse(backend._dashboard_attached)
        self.assertIsNone(backend._sink)


if __name__ == "__main__":
    unittest.main()
