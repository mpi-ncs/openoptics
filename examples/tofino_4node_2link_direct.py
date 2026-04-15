"""Example: 4-node / 2-uplink Tofino optical network with direct routing.

Interactive counterpart of ``tests/tofino_4node_2link_direct_test.py``: same
backend, topology, routing, slice duration, and config — but after deployment
it opens the OpenOptics CLI instead of running a scripted ping.

Physical wiring (openoptics/backends/tofino/config_4tor_2link.local.toml):
  Each logical ToR has 2 OCS uplinks on the SAME Tofino pipe:
    pipe 1 = ToR 0 (server cage 1/0, uplinks 7/0 + 8/0)
    pipe 2 = ToR 1 (server cage 9/0, uplinks 15/0 + 16/0)
    pipe 3 = ToR 2 (no server,       uplinks 23/0 + 24/0)
    pipe 0 = ToR 3 (no server,       uplinks 31/0 + 32/0)
  Servers:
    server 1 (SERVER1_HOST_IP, mgmt SERVER1_MGMT_IP) → ToR 0
    server 2 (SERVER2_HOST_IP, mgmt SERVER2_MGMT_IP) → ToR 1

What this script does:
  1. Deploys a 4-node opera topology (2 uplinks per ToR, with guardband slices)
  2. Computes direct per-hop routing — opera assigns some destinations to
     uplink port 0 and others to port 1 (tor 0 → tor 1 goes via port 0;
     tor 0 → tor 2 goes via port 1).  See the sibling "swap" test for a
     config variant that routes the cross-server ping through port 1.
  3. Installs OCS and ToR tables on the real Tofino switches
  4. Opens the OpenOptics CLI for interactive testing

In the CLI, try:
  server_check                 — verify server connectivity and install ARP
  server_ping 0 1              — ping from server 1 to server 2 through the optical fabric
  h0 ping h1                   — same, via the hN shorthand
"""

import logging
import os

from openoptics import Toolbox, OpticalTopo, OpticalRouting

logging.basicConfig(level=logging.INFO)
logging.getLogger("paramiko").setLevel(logging.WARNING)

if __name__ == "__main__":
    config_file = os.path.join(
        os.path.dirname(__file__),
        "..", "openoptics", "backends", "tofino", "config_4tor_2link.local.toml",
    )

    nb_node = 4
    nb_link = 2

    net = Toolbox.BaseNetwork(
        name="tofino_4node_2link_direct",
        backend="Tofino",
        nb_node=nb_node,
        nb_link=nb_link,
        time_slice_duration_us=50,
        config_file=config_file,
    )

    circuits = OpticalTopo.opera(nb_node=nb_node, nb_link=nb_link, guardband=True)
    assert net.deploy_topo(circuits), "Topology deployment failed"

    paths = OpticalRouting.routing_direct(net.get_topo())
    assert net.deploy_routing(paths, routing_mode="Per-hop"), "Routing deployment failed"

    net.start()
