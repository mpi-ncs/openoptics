"""VLB random RTT analysis: runtime-random intermediate selection.

Uses routing_vlb(random=True) which emits send_port=255 sentinel for the first
hop.  The Tofino data plane picks a random port via Random<> per packet, then
the transit ToR resolves the second hop via cal_port_slice_to_node.

With 500us slices the intermediate-wait is visible in RTT distribution.
"""
import logging
import sys
import time
import re
from openoptics import Toolbox, OpticalTopo, OpticalRouting

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logging.getLogger("paramiko").setLevel(logging.WARNING)

config_file = "/openoptics/openoptics/backends/tofino/config_2tor_2link.toml"

net = Toolbox.BaseNetwork(
    name="tofino_vlb_random",
    backend="Tofino",
    nb_node=4, nb_link=2,
    time_slice_duration_us=500,
    config_file=config_file,
)

circuits = OpticalTopo.opera(nb_node=4, nb_link=2, guardband=True)
assert net.deploy_topo(circuits)
paths = OpticalRouting.routing_vlb(
    net.get_topo(), tor_to_ocs_port=list(range(2)), random=True)
assert net.deploy_routing(paths, routing_mode="Source")

print()
print("=== Server check ===")
results = net._backend.check_servers()

print("=== Wait for NIC links ===")
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
print("=== Ping: 100 pings, 0.2s interval (ToR 0 → ToR 1) ===")
dst_ip = net._backend._tor_to_ip.get(1, "10.29.2.12")
out = net._backend.server_exec(0, f"ping -c 100 -i 0.2 -W 2 {dst_ip} 2>&1")

rtts = []
for line in out.splitlines():
    m = re.search(r'time=(\d+\.?\d*)\s*ms', line)
    if m:
        rtts.append(float(m.group(1)))

print(out.splitlines()[-2] if len(out.splitlines()) >= 2 else "")
print(out.splitlines()[-1] if out.splitlines() else "")

if rtts:
    rtts.sort()
    n = len(rtts)
    print(f"\n=== RTT CDF ({n} samples, slice_duration=500us, random=True) ===")
    print(f"  min:  {rtts[0]:.3f} ms")
    print(f"  p10:  {rtts[int(n*0.10)]:.3f} ms")
    print(f"  p25:  {rtts[int(n*0.25)]:.3f} ms")
    print(f"  p50:  {rtts[int(n*0.50)]:.3f} ms")
    print(f"  p75:  {rtts[int(n*0.75)]:.3f} ms")
    print(f"  p90:  {rtts[int(n*0.90)]:.3f} ms")
    print(f"  p95:  {rtts[int(n*0.95)]:.3f} ms")
    print(f"  max:  {rtts[-1]:.3f} ms")

    print(f"\n=== RTT histogram (0.5ms bins) ===")
    bin_width = 0.5
    max_rtt = max(rtts)
    bins = int(max_rtt / bin_width) + 1
    for b in range(bins):
        lo = b * bin_width
        hi = lo + bin_width
        count = sum(1 for r in rtts if lo <= r < hi)
        bar = '#' * count
        if count > 0:
            print(f"  [{lo:5.1f}, {hi:5.1f}) ms: {count:3d} {bar}")

print()
print("=== Stopping ===")
net.stop_network()
