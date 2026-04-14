"""Example: 4-node / 1-uplink Tofino optical network with VLB + source routing.

Uses deterministic VLB (routing_vlb with random=False): for slices without a
direct link, the source ToR sends through a pre-selected port; the intermediate
ToR forwards to the final destination.  The backend resolves the node-indexed
second hop into concrete (port, slice) at table-generation time.
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
        name="tofino_4node_1link_vlb_source",
        backend="Tofino",
        nb_node=nb_node,
        nb_link=nb_link,
        time_slice_duration_us=50,
        config_file=config_file,
    )

    circuits = OpticalTopo.opera(nb_node=nb_node, nb_link=nb_link, guardband=True)
    assert net.deploy_topo(circuits), "Topology deployment failed"

    paths = OpticalRouting.routing_vlb(
        net.get_topo(), tor_to_ocs_port=list(range(nb_link)))
    assert net.deploy_routing(paths, routing_mode="Source"), "Routing deployment failed"

    net.start()
