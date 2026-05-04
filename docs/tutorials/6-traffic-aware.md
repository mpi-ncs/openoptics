# Tutorial 6: Workflow of Traffic-Aware Architectures

So far, we have used **traffic-oblivious** architectures, where topology schedules are pre-defined and remain fixed regardless of the actual traffic.

Another common approach in optical DCNs is **traffic-aware** topology, where the topology can change at runtime to better match the current traffic patterns.

## Manually Connect and Disconnect

Let’s first try this manually. Run the following script:

```bash
python3 6-traffic-aware-1.py
```
This script creates a network with one fixed topology, where only ToR0–ToR3 and ToR1–ToR2 are directly connected.

Your task is to make `ping` work between `h1` and `h3` by using `connect` and `disconnect` commands in the OpenOptics CLI.

For usage help, run:
```text
OpenOptics> help disconnect
Disconnect two nodes by reconfiguring OCS.

        Usage: disconnect [<time_slice>] <node1> <node2> [<port1> <port2>]
        e.g.   disconnect 0 1 2   or   disconnect 0 h1 h2
```
Example:
- `disconnect 0 0 3`
- `disconnect 0 h0 h3`

Both commands remove the connection at time slice `0` between `h0` and `h3`.

And similarly:
```text
OpenOptics> help connect
Connect two nodes by reconfiguring OCS.

        Usage: connect [<time_slice>] <node1> <node2> [<port1> <port2>]
        e.g.   connect 0 1 2   or   connect 0 h1 h2
```
Example:
- `connect 0 0 3`
- `connect 0 h0 h3`

Both commands add a connection at time slice `0` between `h0` and `h3`.

(Traffic-aware mode runs a single dynamic time slice, so the time-slice
argument must be `0`.)


## Automatic Topology Generation

Manual reconfiguration works, but it would be much better if the network could adapt automatically.

The following script demonstrates this using `OpticalTopo.bipartite_matching` to regenerate topologies from runtime traffic metrics, paired with `OpticalRouting.routing_direct_ta`. `net.start_traffic_aware(...)` reapplies the new topology and routing every `update_interval` seconds.

Run the script with:
```bash
python3 6-traffic-aware-2.py
```

After starting the script, try `ping` between random pairs of nodes.
Observe what happens in the dashboard and in the CLI.

No source code changes are required for this task.