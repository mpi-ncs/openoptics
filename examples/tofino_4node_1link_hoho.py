"""Example: 4-node / 1-uplink Tofino optical network with HoHo routing.

Interactive counterpart of ``tests/tofino_4node_1link_hoho_test.py``: same
backend, topology, slice duration and config as the direct-routing
``tofino_4node_1link_direct.py`` example, but uses HoHo multi-hop routing
(max 2 hops) instead of ``routing_direct``.

Physical wiring (openoptics/backends/tofino/config_4tor.local.toml):
  OCS switch (OCS switch IP in secrets.local.toml):  port 7 ↔ the ToR switch port 7
                                     port 15 ↔ the ToR switch port 15
  ToR switch (ToR switch IP in secrets.local.toml):
    pipe 1 = ToR 0 (server cage 1/0, uplink 7/0)
    pipe 2 = ToR 1 (server cage 9/0, uplink 15/0)
    pipe 3 = ToR 2 (no server,       uplink 23/0)
    pipe 0 = ToR 3 (no server,       uplink 31/0)
  Servers:
    server 1 (SERVER1_HOST_IP, mgmt SERVER1_MGMT_IP) → ToR 0
    server 2 (SERVER2_HOST_IP, mgmt SERVER2_MGMT_IP) → ToR 1

What this script does:
  1. Deploys a 4-node opera topology (1 uplink per ToR, with guardband slices)
  2. Computes HoHo routing with max_hop=2 (packets may wait one hop at an
     intermediate ToR to reach slices when a direct circuit isn't scheduled)
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
        "..", "openoptics", "backends", "tofino", "config_4tor.local.toml",
    )

    nb_node = 4
    nb_link = 1

    net = Toolbox.BaseNetwork(
        name="tofino_4node_1link_hoho",
        backend="Tofino",
        nb_node=nb_node,
        nb_link=nb_link,
        time_slice_duration_us=50,
        config_file=config_file,
    )

    circuits = OpticalTopo.opera(nb_node=nb_node, nb_link=nb_link, guardband=True)
    assert net.deploy_topo(circuits), "Topology deployment failed"

    paths = OpticalRouting.routing_hoho(net.get_topo(), max_hop=2)
    assert net.deploy_routing(paths, routing_mode="Per-hop"), "Routing deployment failed"

    net.start()
