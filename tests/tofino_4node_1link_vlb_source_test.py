"""End-to-end Tofino testbed test: 4 logical ToRs, 1 uplink, VLB + source routing.

Uses deterministic VLB: for slices without a direct link, the source ToR sends
through a pre-selected port; the intermediate ToR forwards to the final
destination using the pre-computed second hop resolved by the backend.

Run from inside the Docker container:
    sudo docker exec -w /openoptics openoptics bash -c \\
        "echo '<jump_host_password>' | python3 tests/tofino_4node_1link_vlb_source_test.py"
"""
import logging
import sys
import time
from openoptics import Toolbox, OpticalTopo, OpticalRouting

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logging.getLogger("paramiko").setLevel(logging.WARNING)

config_file = "/openoptics/openoptics/backends/tofino/config_2tor.toml"

net = Toolbox.BaseNetwork(
    name="tofino_4node_1link_vlb_source",
    backend="Tofino",
    nb_node=4, nb_link=1,
    time_slice_duration_us=50,
    config_file=config_file,
)

circuits = OpticalTopo.opera(nb_node=4, nb_link=1, guardband=True)
assert net.deploy_topo(circuits)
paths = OpticalRouting.routing_vlb(
    net.get_topo(), tor_to_ocs_port=list(range(1)))
assert net.deploy_routing(paths, routing_mode="Source")

print()
print("=== Server check (bring up NICs, ensure IPs, install dummy ARP) ===")
results = net._backend.check_servers()
for tor_id, r in results.items():
    status = "OK" if r["reachable"] else "UNREACHABLE"
    if r["error"]:
        print("  ToR %d (%s): %s -- %s" % (tor_id, r.get("mgmt_ip", "?"), status, r["error"]))
    else:
        nic_info = " on %s" % r["nic"] if r.get("nic") else ""
        ip_status = "configured" if r["ip_configured"] else "MISSING"
        if r.get("ip_added"):
            ip_status = "ADDED"
        print("  ToR %d (%s): %s, %s%s %s" % (tor_id, r.get("mgmt_ip"), status, r["host_ip"], nic_info, ip_status))

print()
print("=== Waiting for server NIC links to come up (max 60s) ===")
nic0 = results[0]["nic"]
nic1 = results[1]["nic"]
for attempt in range(30):
    time.sleep(2)
    state0 = net._backend.server_exec(0, f"cat /sys/class/net/{nic0}/operstate 2>&1").strip()
    state1 = net._backend.server_exec(1, f"cat /sys/class/net/{nic1}/operstate 2>&1").strip()
    print(f"  t={2*(attempt+1):2d}s  tor0:{nic0}={state0}  tor1:{nic1}={state1}")
    if state0 == "up" and state1 == "up":
        break

print()
print("=== Ping: ToR 0 -> ToR 1 (50 pings, 0.2s interval) ===")
dst_ip = net._backend._tor_to_ip.get(1, "10.29.2.12")
try:
    out = net._backend.server_exec(0, "ping -c 50 -i 0.2 -W 2 %s 2>&1" % dst_ip)
    print(out)
except Exception as e:
    print("Error: %s" % e)

print("=== Ping: ToR 1 -> ToR 0 (50 pings, 0.2s interval) ===")
src_ip = net._backend._tor_to_ip.get(0, "10.29.2.13")
try:
    out = net._backend.server_exec(1, "ping -c 50 -i 0.2 -W 2 %s 2>&1" % src_ip)
    print(out)
except Exception as e:
    print("Error: %s" % e)

print()
print("=== Stopping ===")
net.stop_network()
