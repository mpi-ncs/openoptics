# Tutorial 6: Traffic-aware Workflow

Previously, we were running traffic oblivious architectures where topology schedules are pre-defined regardless of running traffic.

It is also a popular optical DCN scheme to change topology at runtime to fit traffic pattern.

## Manually Connect and Disconnect

First, let's do it manually.

```bash
python3 tutorials/6-traffic-aware-1.py
```
This script creates a network with one fixed topology.
Only h0-h3 and h1-h2 are connected.

Your task is make `ping` between h1 and h3 work by using `connect` and `disconnect` at OpenOptics CLI.

```bash
OpenOptics> disconnect
Usage: disconnect [<time_slice>] <node1_id> <node2_id> [<port1> <port2>]
```
Example: `disconnect 1 0 3` disconnect h0-h3 connection at time slice 1.


and 
```bash
OpenOptics> connect
Usage: connect [<time_slice>] <node1_id> <node2_id> [<port1> <port2>]
```
Example: `connect 1 0 3` disconnect h0-h3 connection at time slice 1.


## Automatic Topology Generation

It would be nice if things can be more automatic.
The following script uses `OpticalTopo.bipartite_matching` to generate topology based on runtime traffic metrics automatically.

```bash
python3 tutorials/6-traffic-aware-2.py
```

Start the script and ping between h1 and h3, observe what happens at the dashboard and CLI.
No source code need to change for this task.