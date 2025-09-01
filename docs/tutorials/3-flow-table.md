# Tutorial 3: Enable Routing with Flow Tables

After setting up the time-sliced topology, the next step is to implement routing for your network.

In traditional software-defined networks (SDNs), routing is implemented at switches using flow tables.
A flow table is a match-action table that defines how packets are looked up, modified, and forwarded.

Here, we introduce a minimal version of a flow table entry:

```
-------------------------------------
|  Match fields  || Action (forward)|
+----------------||-----------------+
|   Destination  ||    Send Port    |
-------------------------------------
```
For example, at ToR0, the following flow table entry:
```
-------------------------------------
|  Match fields  || Action (forward)|
+----------------||-----------------+
|     Dst: 1     ||   Send Port: 0  |
-------------------------------------
```
instructs the switch to forward packets destined for node 1 out of port 0.


## Define Flow Table Entries in OpenOptics

With OpenOptics, the above entry can be defined as:

```python
TimeFlowEntry(dst=1, hops=TimeFlowHop(send_port=0))
```

You can then add this flow table entry to a ToR switch (indexed by its node_id) using:

```python
net.add_time_flow_entry(node_id, entry)
```

Please note that the above entry will be loaded at **ToR switches**, not OCSes.
OCS does nothing else but transmitting received packets to a port based on the topology schedule.

## Your Tasks

You will now enable routing in your optical DCN:

1. Add flow table entries for nodes 0 and 1 to enable routing between them.
2. Test reachability with ping: `h0 ping h1`, check packets' sequence numbers `icmp_seq`, and reason the packet loss.
3. To reduce packet loss, you could add flow table entries for nodes 2 and 3.
4. Test reachability again with ping: `h0 ping h1`, and check icmp_seq now.

Run the script and test your solution in the CLI with `OpenOptics> h0 ping h1`:
```python
python3 3-flow-table.py
```