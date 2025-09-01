# Tutorial 4: Improve Routing with Time Flow Tables

The previous routing is not ideal for optical DCNs because flow tables are not time-aware.
As the optical DCN has time-sliced topology, the forwarding table should also be time-aware.

Therefore, OpenOptics provides time flow table entry:
```
+------------------------------------- ------------------------------------+
|            Match Fields              ||        Action (forward)          |
+--------------------------------------||----------------------------------+
|  Destination   | Arrival Time Slice  ||   Send Port  |  Send Time Slice  |
+--------------------------------------------------------------------------+
```

Compared to the previous flow table entry, the time flow table entry has two additional fields:

**Arrival Time Slice**: The time slice at which the packet arrives at the switch.

**Send Time Slice**: The time slice at which the packet should be sent out of the switch.


## Define Time Flow Table Entries in OpenOptics

With OpenOptics, time flow table entry can be defined as:

```python
TimeFlowEntry(dst=1, arrival_ts=0, hops=TimeFlowHop(send_port=0, send_ts=1))
```

Meaning the packets that arrive at the ToR at time slice 0, should be are sent out from port 0 at time slice 1.

```{note}
To enforce the above time flow table entry, the underlying switch implementation should support buffering
packet until a certain time slice.
The switch implementation for the Mininet backend is a P4 software switch, [bmv2](https://github.com/p4lang/behavioral-model).
OpenOptics is shipped with a modified bmv2 implementation to support time-based buffering.
```

## Your Tasks

You will improve the routing in your optical DCN:

1. Add time flow table entries for nodes 0 and 1 to enable routing between them.
2. In the `ping` test, no packet loss or reordering should be observed.

Run the script and test your solution in the CLI with `OpenOptics> h0 ping h1`:
```python
python3 4-time-flow-table.py
```