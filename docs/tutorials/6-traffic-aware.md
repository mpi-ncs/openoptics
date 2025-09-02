# Tutorial 6: Workflow of Traffic-Aware Architectures

So far, we have used **traffic-oblivious** architectures, where topology schedules are pre-defined and remain fixed regardless of the actual traffic.

Another common approach in optical DCNs is **traffic-aware** topology, where the topology can change at runtime to better match the current traffic patterns.

## Manually Connect and Disconnect

Let’s first try this manually. Run the following script:

```bash
python3 6-traffic-aware-1.py
```
This script creates a network with one fixed topology, where only `h0-h3` and `h1-h2` are connected.

Your task is to make `ping` work between h1 and h3 by using `connect` and `disconnect` commands in the OpenOptics CLI.

```bash
OpenOptics> disconnect
Usage: disconnect [<time_slice>] <node1_id> <node2_id> [<port1> <port2>]
```
Example: 
- `disconnect 1 0 3`
- `disconnect 1 h0 h3` 
Both commands remove the connection at time slice `1` between `h0` and `h3`.


and 
```bash
OpenOptics> connect
Usage: connect [<time_slice>] <node1_id> <node2_id> [<port1> <port2>]
```
Example:
- `connect 1 0 3`
- `connect 1 h0 h3` 
Both commands add a connection at time slice `1` between `h0` and `h3`.


## Automatic Topology Generation

Manual reconfiguration works, but it would be much better if the network could adapt automatically.

The following script demonstrates this using `OpticalTopo.bipartite_matching` which generates topologies dynamically based on runtime traffic metrics, and using `net.start_traffic_aware(OpticalTopo.bipartite_matching, update_interval=2)` to configure topology update condition, e.g. every 2 seconds.

Run the script with:
```bash
python3 tutorials/6-traffic-aware-2.py
```

After starting the script, try `ping` between random pairs of nodes.
Observe what happens in the dashboard and in the CLI.

No source code changes are required for this task.