"""Example: 4-node / 2-uplink Tofino optical network with VLB + source routing.

Uses runtime-random VLB (routing_vlb with random=True): for slices without a
direct link, the source ToR picks a random uplink port via Tofino's Random<>
primitive.  The intermediate ToR resolves the final hop via
cal_port_slice_to_node.

Requires config_4tor_2link.local.toml (2 OCS uplinks per ToR) so that Random<>
has a meaningful choice between port 0 and port 1.
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
        name="tofino_4node_2link_vlb_source",
        backend="Tofino",
        nb_node=nb_node,
        nb_link=nb_link,
        time_slice_duration_us=500,
        config_file=config_file,
    )

    circuits = OpticalTopo.opera(nb_node=nb_node, nb_link=nb_link, guardband=True)
    assert net.deploy_topo(circuits), "Topology deployment failed"

    paths = OpticalRouting.routing_vlb(
        net.get_topo(), tor_to_ocs_port=list(range(nb_link)), random=True)
    assert net.deploy_routing(paths, routing_mode="Source"), "Routing deployment failed"

    net.start()
