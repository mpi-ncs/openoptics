"""ns-3 version of mininet_routing_direct_perhop.py.

Drives the same 4-ToR round-robin + direct per-hop routing pipeline through
the ns-3 backend instead of Mininet. Requires `openoptics-install-ns3` to
have been run and `NS3_DIR` / `PYTHONPATH` exported as the helper prints.

The only user-visible differences vs. the Mininet example:

* no interactive CLI — the ns-3 backend short-circuits ``start_cli()`` and
  just runs the simulator for ``simulation_stop_s`` seconds;
* traffic is specified up front via the ns-3 traffic builder instead of
  being generated interactively with ``h0 ping h1``;
* dashboard telemetry comes from ns-3 TraceSources on each OcsApp/TorApp,
  sampled at sub-slice cadence so short-lived calendar-queue occupancy is
  visible.

After ``Simulator::Run()`` finishes, the script pauses for Enter so the
dashboard stays up and the user can explore the charts. Set
``OPENOPTICS_NS3_NO_PAUSE=1`` (or redirect stdin) to skip the pause for
scripted / CI runs.
"""

from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    nb_node = 4
    # ns-3 is a discrete-event sim so we use shorter slices than the
    # Mininet example (1024ms there) to cycle through the round-robin
    # schedule quickly. Sample faster than the slice clock so packets waiting
    # for a future slice show up in the dashboard queue-depth chart.
    net = Toolbox.BaseNetwork(
        name="ns3_routing_direct_perhop",
        backend="ns3",
        nb_node=nb_node,
        time_slice_duration_us=10_000,      # 10 ms per slice
        snapshot_interval_us=1_000,         # 1 ms dashboard snapshots
        guardband_ms=0,                     # no OCS reconfig time modelled
        ocs_tor_link_bw_gbps=100,
        tor_host_link_bw_gbps=100,
        use_webserver=True,                 # M4: dashboard enabled
        simulation_stop_s=1.0,
    )
    circuits = OpticalTopo.round_robin(nb_node=nb_node)
    assert net.deploy_topo(circuits)
    paths = OpticalRouting.routing_direct(net.get_topo())
    net.deploy_routing(paths, routing_mode="Per-hop")

    # Traffic: h0 -> h1, echoed back. The 45 ms start phase lands the burst
    # in slice 1 while direct routing for 0->1 transmits in slice 2. A 1 ms
    # interval keeps adding packets during slice 0/1 wait windows, so the
    # dashboard shows a real queue buildup instead of a single queued packet.
    # Echoes prove the full round-trip
    # (host0 -> tor0 -> OCS -> tor1 -> host1 -> back) worked.
    net.udp_traffic() \
        .echo(0, 1, start_s=0.045, stop_s=0.8,
              num_packets=200, interval_s=0.001) \
        .install()
    net.start()
