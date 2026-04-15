"""Example: 4-node / 1-uplink Tofino optical network with HoHo + source routing.

Same topology and routing algorithm as tofino_4node_1link_hoho.py but uses
`routing_mode="Source"` instead of `"Per-hop"`. With source routing the entire
path (up to 2 hops) is computed at the source ToR and packed into the packet
header (hdr.sr_entry) so intermediate ToRs forward without re-running the
routing table. See docs/tofino-backend.md and openoptics/backends/mininet/p4src/tor/tor.p4 for the design.
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
        name="tofino_4node_1link_hoho_source",
        backend="Tofino",
        nb_node=nb_node,
        nb_link=nb_link,
        time_slice_duration_us=50,
        config_file=config_file,
    )

    circuits = OpticalTopo.opera(nb_node=nb_node, nb_link=nb_link, guardband=True)
    assert net.deploy_topo(circuits), "Topology deployment failed"

    paths = OpticalRouting.routing_hoho(net.get_topo(), max_hop=2)
    assert net.deploy_routing(paths, routing_mode="Source"), "Routing deployment failed"

    net.start()
