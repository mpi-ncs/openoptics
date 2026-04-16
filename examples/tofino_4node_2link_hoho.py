"""Example: 4-node / 2-uplink Tofino optical network with HoHo routing.

Interactive counterpart of ``tests/tofino_4node_2link_hoho_test.py``: same
backend, topology, slice duration and config as the direct-routing
``tofino_4node_2link_direct.py`` example, but uses HoHo multi-hop routing
(max 2 hops) instead of ``routing_direct``.

Physical wiring (expects ./openoptics-tofino.toml in cwd — for 2-uplink
testbeds, adjust `tor_ocs_port_pairs` to list two ports per ToR. Override
the path with OPENOPTICS_CONFIG=/path/to/cfg.toml):
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
    config_file = os.environ.get("OPENOPTICS_CONFIG", "openoptics-tofino.toml")

    nb_node = 4
    nb_link = 2

    net = Toolbox.BaseNetwork(
        name="tofino_4node_2link_hoho",
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
