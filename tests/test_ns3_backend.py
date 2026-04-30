# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# License: Creative Commons NC BY SA 4.0
#
# Ns3Backend integration tests. Validates the BackendBase surface and the
# end-to-end h0→h1 UDP traffic path using the real contrib module.

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from unittest.mock import patch

from tests.ns3_helpers import skip_if_no_ns3, ns3_available
from tests.helpers import FakeBackend


class BackendErrorTests(unittest.TestCase):
    """Regression guards that don't need ns-3 installed."""

    def test_cq_buffer_bytes_is_the_only_public_cq_limit_kwarg(self):
        from openoptics.backends.ns3.backend import Ns3Backend

        accepted = Ns3Backend.accepted_kwargs()
        self.assertIn("cq_buffer_bytes", accepted)
        old_name = "cq_capacity" + "_per_slice"
        self.assertNotIn(old_name, accepted)

    def test_create_backend_without_ns3_dir_raises(self):
        from openoptics.backends import create_backend

        # Isolate from both env and the recorded `ns3_env.json` fallback —
        # `Ns3Backend.__init__` reads `$OPENOPTICS_STATE_DIR/ns3_env.json`
        # (default `~/.openoptics/...`) when `NS3_DIR` is unset, so a
        # developer who has run `openoptics-install-ns3` would otherwise
        # see this test pass through the fallback instead of raising.
        saved_ns3_dir = os.environ.pop("NS3_DIR", None)
        saved_state_dir = os.environ.get("OPENOPTICS_STATE_DIR")
        try:
            with tempfile.TemporaryDirectory() as empty_state_dir:
                os.environ["OPENOPTICS_STATE_DIR"] = empty_state_dir
                with self.assertRaises(Exception) as ctx:
                    create_backend("ns3")
            # Error message must surface the helper name so users know what to do.
            self.assertIn("openoptics-install-ns3", str(ctx.exception))
        finally:
            if saved_ns3_dir is not None:
                os.environ["NS3_DIR"] = saved_ns3_dir
            if saved_state_dir is None:
                os.environ.pop("OPENOPTICS_STATE_DIR", None)
            else:
                os.environ["OPENOPTICS_STATE_DIR"] = saved_state_dir


class InstallCliTests(unittest.TestCase):
    """Regression guards on the `openoptics-install-ns3` CLI output.

    Runs without ns-3 installed (the installer's --print-env-only path
    never imports `ns`).
    """

    def test_print_env_only_is_shell_evaluable(self):
        """`eval $(... --print-env-only /tmp/fake)` must set NS3_DIR."""
        import shutil
        import subprocess

        sh = shutil.which("sh")
        if not sh:
            self.skipTest("/bin/sh not available")

        fake_dir = "/tmp/openoptics-install-ns3-test-dir"
        cmd = (
            f'eval "$({sys.executable} -m openoptics.backends.ns3.install '
            f'--print-env-only {fake_dir})" && '
            f'printf "NS3_DIR=%s\\nPYTHONPATH=%s\\n" "$NS3_DIR" "$PYTHONPATH"'
        )
        env = dict(os.environ)
        env.pop("NS3_DIR", None)
        env["PYTHONPATH"] = env.get(
            "PYTHONPATH",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        )
        result = subprocess.run(
            [sh, "-c", cmd], capture_output=True, text=True, env=env,
        )
        self.assertEqual(
            result.returncode, 0,
            f"shell eval failed: stdout={result.stdout!r} "
            f"stderr={result.stderr!r}",
        )
        self.assertIn(f"NS3_DIR={fake_dir}", result.stdout)
        self.assertIn(f"{fake_dir}/build/bindings/python", result.stdout)

    def test_print_env_only_emits_no_prose(self):
        """Every line from --print-env-only must start with 'export '."""
        import subprocess

        result = subprocess.run(
            [
                sys.executable, "-m", "openoptics.backends.ns3.install",
                "--print-env-only", "/tmp/fake",
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            self.assertTrue(
                stripped.startswith("export "),
                f"non-export line leaked: {line!r}",
            )


class OcsPortEncodingTests(unittest.TestCase):
    """The ns-3 backend's OCS port index must match Toolbox's encoding.

    Toolbox emits schedule entries via
    ``BaseNetwork.cal_node_port_to_ocs_port(node_id, port_id) =
    port_id * nb_node + node_id`` (port-major). If the ns-3 side registers
    OCS devices in a different order, nb_link>1 topologies silently
    misroute packets. This is a pure-Python guard so the encoding break
    is caught even in CI environments without ns-3 bindings.
    """

    def test_encoding_matches_toolbox(self):
        from openoptics.Toolbox import BaseNetwork
        from openoptics.backends.ns3.backend import ocs_port_index
        from tests.helpers import FakeBackend

        for nb_node, nb_link in [(2, 1), (4, 1), (4, 2), (8, 3)]:
            backend = FakeBackend(nb_node=nb_node)
            with patch(
                "openoptics.Toolbox.create_backend", return_value=backend
            ):
                net = BaseNetwork(
                    name="enc",
                    backend="Mininet",   # irrelevant; FakeBackend intercepts
                    nb_node=nb_node,
                    nb_link=nb_link,
                    time_slice_duration_us=10_000,
                    use_webserver=False,
                )
            for tor_id in range(nb_node):
                for link_id in range(nb_link):
                    self.assertEqual(
                        net.cal_node_port_to_ocs_port(tor_id, link_id),
                        ocs_port_index(tor_id, link_id, nb_node),
                        msg=(
                            f"Toolbox vs ns-3 OCS port index disagree at "
                            f"(nb_node={nb_node}, nb_link={nb_link}, "
                            f"tor={tor_id}, link={link_id})"
                        ),
                    )


@skip_if_no_ns3
class BackendSetupTests(unittest.TestCase):
    """Surface-level properties of a freshly set-up ns-3 backend."""

    def tearDown(self):
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    def test_setup_populates_caches(self):
        from openoptics import OpticalTopo, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        nb_node = 4
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="setup_test", backend="ns3", nb_node=nb_node,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))

        self.assertEqual(
            backend.get_ip_to_tor(),
            {f"10.0.{i}.1": i for i in range(nb_node)},
        )
        self.assertEqual(len(backend.get_tor_switches()), nb_node)
        for i in range(nb_node):
            self.assertTrue(backend.switch_exists(f"tor{i}"))
        self.assertTrue(backend.switch_exists("ocs"))
        self.assertEqual(
            [h.name for h in backend.get_tor_switches()],
            [f"tor{i}" for i in range(nb_node)],
        )
        backend.stop()
        backend.cleanup()

    def test_cq_buffer_bytes_must_be_positive(self):
        from openoptics import OpticalTopo, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="bad_cq_buffer", backend="ns3", nb_node=4,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False, cq_buffer_bytes=0,
            )
            with self.assertRaisesRegex(ValueError, "cq_buffer_bytes"):
                net.deploy_topo(OpticalTopo.round_robin(nb_node=4))
        backend.cleanup()


@skip_if_no_ns3
class BackendParityTests(unittest.TestCase):
    """Verify the TableEntry stream reaching Ns3Backend matches FakeBackend."""

    def tearDown(self):
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    @staticmethod
    def _run_pipeline(backend, nb_node=4):
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="parity_test", backend="ns3", nb_node=nb_node,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))
            paths = OpticalRouting.routing_direct(net.get_topo())
            net.deploy_routing(paths, routing_mode="Per-hop")
        return net

    def test_tableentry_format_parity_with_fake(self):
        """Ns3Backend should receive the same (table, action, keys, params)
        stream as FakeBackend for an identical Toolbox pipeline."""
        from openoptics.backends.ns3.backend import Ns3Backend

        # Wrap Ns3Backend.load_table to capture what it receives, without
        # disturbing the real dispatch.
        recorded_ns3: list = []

        ns3_backend = Ns3Backend()
        real_load = ns3_backend.load_table

        def capture_load(switch_name, entries, **kwargs):
            # Record a (switch, [(table, action, match_keys, action_params)])
            # tuple per call, matching FakeBackend.loaded's structure but in
            # a canonical comparable form.
            recorded_ns3.append(
                (switch_name, [
                    (e.table, e.action, dict(e.match_keys),
                     dict(e.action_params), e.is_default_action)
                    for e in entries
                ])
            )
            return real_load(switch_name, entries, **kwargs)

        ns3_backend.load_table = capture_load

        fake = FakeBackend(nb_node=4)
        fake_recorded = []
        real_fake_load = fake.load_table

        def fake_capture(switch_name, entries, **kwargs):
            fake_recorded.append(
                (switch_name, [
                    (e.table, e.action, dict(e.match_keys),
                     dict(e.action_params), e.is_default_action)
                    for e in entries
                ])
            )
            return real_fake_load(switch_name, entries, **kwargs)

        fake.load_table = fake_capture

        # Run both pipelines with identical settings.
        self._run_pipeline(ns3_backend)
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        with patch("openoptics.Toolbox.create_backend", return_value=fake):
            net = Toolbox.BaseNetwork(
                name="fake_pipe", backend="Mininet", nb_node=4,
                time_slice_duration_us=10_000, use_webserver=False,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=4))
            paths = OpticalRouting.routing_direct(net.get_topo())
            net.deploy_routing(paths, routing_mode="Per-hop")

        self.assertEqual(recorded_ns3, fake_recorded)
        ns3_backend.stop()
        ns3_backend.cleanup()


@skip_if_no_ns3
class BackendEndToEndTests(unittest.TestCase):
    """Full-pipeline tests — host -> tor -> ocs -> tor -> host UDP echo."""

    def tearDown(self):
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    def test_end_to_end_udp_with_example_settings(self):
        """Drive the full pipeline with settings from examples/ and assert
        UDP echo replies arrive back at the source host, no drops."""
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        nb_node = 4
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="e2e_test", backend="ns3", nb_node=nb_node,
                time_slice_duration_us=10_000,  # 10ms / slice
                guardband_ms=0,
                use_webserver=False,
                simulation_stop_s=1.0,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))
            paths = OpticalRouting.routing_direct(net.get_topo())
            net.deploy_routing(paths, routing_mode="Per-hop")

            net.udp_traffic().echo(
                0, 1,
                start_s=0.05, stop_s=0.8,
                num_packets=20, interval_s=0.03,
            ).install()
            net.start()

        self.assertGreater(backend._tor_apps[0].GetIngressFromHostCount(), 0)
        self.assertGreater(backend._tor_apps[0].GetForwardedCount(), 0)
        self.assertGreater(backend._ocs_app.GetForwardCount(), 0)
        self.assertGreater(backend._tor_apps[1].GetDeliveredToHostCount(), 0)
        # Echo replies must make it home.
        self.assertGreater(backend._tor_apps[0].GetDeliveredToHostCount(), 0)

        self.assertEqual(backend._ocs_app.GetDropCount(), 0)
        self.assertEqual(backend._tor_apps[0].GetDropCount(), 0)
        self.assertEqual(backend._tor_apps[1].GetDropCount(), 0)

        backend.cleanup()

    def test_end_to_end_udp_with_nonmatching_slice(self):
        """Burst starts mid-slice; calendar queue should hold packets until
        the matching slice fires. No packets should be dropped and all
        should be delivered eventually."""
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        nb_node = 4
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="e2e_deferred", backend="ns3", nb_node=nb_node,
                time_slice_duration_us=10_000,
                guardband_ms=0,
                use_webserver=False,
                simulation_stop_s=2.0,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))
            paths = OpticalRouting.routing_direct(net.get_topo())
            net.deploy_routing(paths, routing_mode="Per-hop")
            # Pick an (src, dst) whose circuit is active in a later slice, so
            # the first packets have to wait. round_robin(4): (1->3) in slice 1.
            net.udp_traffic().echo(
                1, 3, start_s=0.001,
                stop_s=0.5, num_packets=10, interval_s=0.02,
            ).install()
            net.start()

        self.assertEqual(
            backend._tor_apps[1].GetDropCount() + backend._ocs_app.GetDropCount(),
            0,
            "no drops expected on a non-saturated workload",
        )
        self.assertGreater(backend._tor_apps[3].GetDeliveredToHostCount(), 0)
        self.assertGreater(backend._tor_apps[1].GetDeliveredToHostCount(), 0)

        backend.cleanup()


@skip_if_no_ns3
class BackendReportTests(unittest.TestCase):
    """Post-run CLI report: FlowMonitor + per-switch counters."""

    def tearDown(self):
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    def _run_basic_scenario(self, use_webserver=False):
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        os.environ["OPENOPTICS_NS3_NO_PAUSE"] = "1"
        nb_node = 4
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="report_test", backend="ns3", nb_node=nb_node,
                time_slice_duration_us=10_000,
                guardband_ms=0,
                use_webserver=use_webserver,
                simulation_stop_s=0.3,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))
            net.deploy_routing(
                OpticalRouting.routing_direct(net.get_topo()),
                routing_mode="Per-hop",
            )
            net.udp_traffic().echo(
                0, 1, start_s=0.01, stop_s=0.25,
                num_packets=5, interval_s=0.02,
            ).install()
            net.start()
        return backend, net

    def test_report_covers_expected_sections(self):
        """Basic structural check: report includes both sections + totals."""
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            backend, _ = self._run_basic_scenario()
        out = buf.getvalue()

        self.assertIn("OpenOptics ns-3 Simulation Report", out)
        self.assertIn("Per-switch counters", out)
        self.assertIn("Per-flow end-to-end (FlowMonitor)", out)
        self.assertIn("Totals:", out)
        # Flow 5-tuple string appears for the 10.0.0.1 -> 10.0.1.1 direction.
        self.assertIn("10.0.0.1", out)
        self.assertIn("10.0.1.1", out)
        backend.cleanup()

    def test_report_reflects_actual_counters(self):
        """Values printed in the per-switch row must match the C++ counters
        at the moment the report was generated."""
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            backend, _ = self._run_basic_scenario()
        out = buf.getvalue()

        # Every packet should make it through in this non-saturated case.
        # tor0 has 5 ingress-from-host packets (from the UdpEchoClient).
        from_host_tor0 = int(backend._tor_apps[0].GetIngressFromHostCount())
        self.assertEqual(from_host_tor0, 5)
        # The report row for tor0 should include that count as one of the
        # whitespace-separated numeric columns.
        tor0_line = next(
            line for line in out.splitlines() if line.strip().startswith("tor0")
        )
        self.assertIn(str(from_host_tor0), tor0_line)
        backend.cleanup()

    def test_report_suppressed_by_env(self):
        """OPENOPTICS_NS3_NO_REPORT=1 silences the report entirely."""
        import io
        import contextlib

        os.environ["OPENOPTICS_NS3_NO_REPORT"] = "1"
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                backend, _ = self._run_basic_scenario()
        finally:
            os.environ.pop("OPENOPTICS_NS3_NO_REPORT", None)

        out = buf.getvalue()
        self.assertNotIn("OpenOptics ns-3 Simulation Report", out)
        backend.cleanup()

    def test_print_report_reentrant(self):
        """Calling print_report() manually after run() should be safe."""
        import io
        import contextlib

        backend, _ = self._run_basic_scenario()
        # Suppress the report emitted during run() by redirecting once.
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            backend.print_report()
        out = buf2.getvalue()
        self.assertIn("OpenOptics ns-3 Simulation Report", out)
        backend.cleanup()


@skip_if_no_ns3
class BackendLinkDelayTests(unittest.TestCase):
    """Guardband + split propagation delay kwargs."""

    def tearDown(self):
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    def test_link_delay_us_shorthand_sets_both(self):
        """`link_delay_us` alone should populate both host and ocs delays."""
        from openoptics import OpticalTopo, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        os.environ["OPENOPTICS_NS3_NO_PAUSE"] = "1"
        os.environ["OPENOPTICS_NS3_NO_REPORT"] = "1"
        try:
            backend = Ns3Backend()
            with patch("openoptics.Toolbox.create_backend", return_value=backend):
                net = Toolbox.BaseNetwork(
                    name="shorthand", backend="ns3", nb_node=4,
                    time_slice_duration_us=10_000, guardband_ms=0,
                    use_webserver=False, simulation_stop_s=0.05,
                    link_delay_us=15,   # shorthand only
                )
                net.deploy_topo(OpticalTopo.round_robin(nb_node=4))
            self.assertEqual(backend._host_link_delay_us, 15)
            self.assertEqual(backend._ocs_link_delay_us, 15)
            backend.cleanup()
        finally:
            os.environ.pop("OPENOPTICS_NS3_NO_REPORT", None)

    def test_per_link_overrides_win_over_shorthand(self):
        """Explicit host/ocs kwargs override the shorthand."""
        from openoptics import OpticalTopo, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        os.environ["OPENOPTICS_NS3_NO_PAUSE"] = "1"
        os.environ["OPENOPTICS_NS3_NO_REPORT"] = "1"
        try:
            backend = Ns3Backend()
            with patch("openoptics.Toolbox.create_backend", return_value=backend):
                net = Toolbox.BaseNetwork(
                    name="override", backend="ns3", nb_node=4,
                    time_slice_duration_us=10_000, guardband_ms=0,
                    use_webserver=False, simulation_stop_s=0.05,
                    link_delay_us=15,       # shorthand
                    host_link_delay_us=3,   # explicit wins
                    ocs_link_delay_us=25,   # explicit wins
                )
                net.deploy_topo(OpticalTopo.round_robin(nb_node=4))
            self.assertEqual(backend._host_link_delay_us, 3)
            self.assertEqual(backend._ocs_link_delay_us, 25)
            backend.cleanup()
        finally:
            os.environ.pop("OPENOPTICS_NS3_NO_REPORT", None)

    def test_host_and_ocs_link_delays_apply_on_wire(self):
        """A large ocs_link_delay should show up in FlowMonitor end-to-end
        delay as a lower bound: each round trip crosses the OCS uplink 4
        times (tor0→ocs, ocs→tor1, tor1→ocs, ocs→tor0), so min delay is
        at least 4 * ocs_link_delay_us + 4 * host_link_delay_us."""
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        os.environ["OPENOPTICS_NS3_NO_PAUSE"] = "1"
        os.environ["OPENOPTICS_NS3_NO_REPORT"] = "1"
        try:
            host_delay_us = 5
            ocs_delay_us = 25
            backend = Ns3Backend()
            with patch("openoptics.Toolbox.create_backend", return_value=backend):
                net = Toolbox.BaseNetwork(
                    name="delays", backend="ns3", nb_node=4,
                    time_slice_duration_us=10_000, guardband_ms=0,
                    use_webserver=False, simulation_stop_s=0.3,
                    host_link_delay_us=host_delay_us,
                    ocs_link_delay_us=ocs_delay_us,
                )
                net.deploy_topo(OpticalTopo.round_robin(nb_node=4))
                net.deploy_routing(
                    OpticalRouting.routing_direct(net.get_topo()),
                    routing_mode="Per-hop",
                )
                net.udp_traffic().echo(
                    0, 1, start_s=0.01, stop_s=0.25,
                    num_packets=5, interval_s=0.02,
                ).install()
                net.start()

            # Pull FlowMonitor stats directly.
            ns = backend._ns
            backend._flow_monitor.CheckForLostPackets()
            stats = backend._flow_monitor.GetFlowStats()
            min_delay_ns = None
            for _flow_id, s in stats:
                if int(s.rxPackets) > 0:
                    d = s.minDelay.GetNanoSeconds()
                    min_delay_ns = d if min_delay_ns is None else min(min_delay_ns, d)
            self.assertIsNotNone(min_delay_ns, "expected at least one received flow")
            # Round trip crosses each type of link twice per direction (2
            # host links and 2 ocs links each way), so >= 2*host + 2*ocs
            # propagation delay for a one-way trip.
            expected_min_ns = (2 * host_delay_us + 2 * ocs_delay_us) * 1000
            self.assertGreaterEqual(
                min_delay_ns, expected_min_ns,
                f"min one-way delay {min_delay_ns} ns below expected "
                f"propagation floor {expected_min_ns} ns",
            )
            backend.cleanup()
        finally:
            os.environ.pop("OPENOPTICS_NS3_NO_REPORT", None)


if __name__ == "__main__":
    unittest.main()
