"""End-to-end Tofino testbed test: 4 logical ToRs, 2 uplinks each, direct routing.

Variant of tofino_4node_2link_direct_test.py that exercises the SECOND uplink
per ToR pipe (cages 8/0 ↔ 16/0) instead of the first (cages 7/0 ↔ 15/0).

How: opera(nb_node=4, nb_link=2) assigns (tor 0 → tor 1) to port 0 and
(tor 0 → tor 2) to port 1.  By relabeling the server-attached pipes as
tor_id 0 and tor_id 2 (instead of 0 and 1), the cross-server ping path
traverses port 1 — proving the second physical uplink is wired and
forwarding correctly.

  * backend     : Tofino
  * topology    : opera(nb_node=4, nb_link=2, guardband=True)
  * routing     : routing_direct (Per-hop mode)
  * slice       : 50 us per time slice
  * arch        : direct
  * config      : openoptics/backends/tofino/config_2tor_2link_swap.toml
                  pipe 1=tor_id 0 (server), pipe 2=tor_id 2 (server),
                  pipe 3=tor_id 1, pipe 0=tor_id 3.

Verification:
  1. server NICs come up; data-plane IPs assigned; dummy ARP installed.
  2. Both pings (s13 ↔ s12) succeed at ~0.5 ms RTT, 0% loss.
  3. `ucli pm show` on the ToR switch reports non-zero TX on cages 8/0 and
     16/0 (the *second* uplink on each server-attached pipe), confirming
     the second uplink actually carries data traffic.

Run from inside the Docker container:
    sudo docker exec -w /openoptics openoptics bash -c \\
        "echo '<jump_host_password>' | python3 tests/tofino_4node_2link_swap_direct_test.py"
"""
import logging
import sys
import time
from openoptics import Toolbox, OpticalTopo, OpticalRouting

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logging.getLogger("paramiko").setLevel(logging.WARNING)

config_file = "/openoptics/openoptics/backends/tofino/config_2tor_2link_swap.toml"

net = Toolbox.BaseNetwork(
    name="tofino_4node_2link_swap_ping",
    backend="Tofino",
    nb_node=4, nb_link=2,
    time_slice_duration_us=50,
    config_file=config_file,
)

circuits = OpticalTopo.opera(nb_node=4, nb_link=2, guardband=True)
assert net.deploy_topo(circuits)
paths = OpticalRouting.routing_direct(net.get_topo())
assert net.deploy_routing(paths, routing_mode="Per-hop")

print()
print("=== Server check (bring up NICs, ensure IPs, install dummy ARP) ===")
results = net._backend.check_servers()
# In the swapped config, the server-attached logical tor_ids are 0 and 2
# (rather than 0 and 1), so iterate the actual results dict.
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

# The two server-attached logical tor_ids (0 and 2 in this swapped config).
server_tor_ids = sorted(results.keys())
src_tor, dst_tor = server_tor_ids[0], server_tor_ids[1]
nic_src = results[src_tor]["nic"]
nic_dst = results[dst_tor]["nic"]

print()
print(f"=== Waiting for server NIC links to come up (max 60s) ===")
for attempt in range(30):
    time.sleep(2)
    state_src = net._backend.server_exec(src_tor, f"cat /sys/class/net/{nic_src}/operstate 2>&1").strip()
    state_dst = net._backend.server_exec(dst_tor, f"cat /sys/class/net/{nic_dst}/operstate 2>&1").strip()
    print(f"  t={2*(attempt+1):2d}s  tor{src_tor}:{nic_src}={state_src}  tor{dst_tor}:{nic_dst}={state_dst}")
    if state_src == "up" and state_dst == "up":
        break

src_ip = net._backend._tor_to_ip[src_tor]
dst_ip = net._backend._tor_to_ip[dst_tor]

print()
print(f"=== Ping: ToR {src_tor} ({src_ip}) -> ToR {dst_tor} ({dst_ip}) ===")
try:
    out = net._backend.server_exec(src_tor, "ping -c 5 -W 2 %s 2>&1" % dst_ip)
    print(out)
except Exception as e:
    print("Error: %s" % e)

print(f"=== Ping: ToR {dst_tor} ({dst_ip}) -> ToR {src_tor} ({src_ip}) ===")
try:
    out = net._backend.server_exec(dst_tor, "ping -c 5 -W 2 %s 2>&1" % src_ip)
    print(out)
except Exception as e:
    print("Error: %s" % e)

# Verify cages 8/0 and 16/0 (the *second* uplink on each server-attached pipe)
# carried non-zero TX, by inspecting per-port counters via ucli pm show.
print()
print("=== ucli pm show on tor switch (verify port 1 of each pipe TX > 0) ===")
deployer = net._backend._deployer
tor_ssh = deployer._ssh_clients.get("tor0")
if tor_ssh:
    chan = tor_ssh.invoke_shell()
    chan.settimeout(2.0)
    time.sleep(0.5)
    try:
        while True:
            chan.recv(8192)
    except Exception:
        pass
    chan.send("source /home/p4/bf-sde-9.12.0/set_sde.bash\n")
    time.sleep(0.5)
    chan.send("/home/p4/bf-sde-9.12.0/install/bin/bfshell\n")
    time.sleep(2.0)
    chan.send("ucli\n")
    time.sleep(1.0)
    chan.send("pm show\n")
    time.sleep(3.0)
    chan.send("exit\n")
    time.sleep(0.5)
    chan.send("exit\n")
    time.sleep(0.5)
    chan.send("exit\n")
    out_buf = b""
    end = time.time() + 5
    while time.time() < end:
        try:
            data = chan.recv(8192)
            if not data:
                break
            out_buf += data
        except Exception:
            break
    print(out_buf.decode(errors="replace"))
    chan.close()

print()
print("=== Stopping ===")
net.stop_network()
