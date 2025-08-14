import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import OpticalTopo, Toolbox

if __name__ == "__main__":
    net = Toolbox.BaseNetwork(
        name="opera",
        backend="Mininet",
        nb_node=27,
        time_slice_duration_ms=256,  # in ms
        use_webserver=True,
    )

    circuits = OpticalTopo.shale(27, 3)

    print(circuits)
    assert net.deploy_topo(circuits)

    net.start()
