# Tutorial 4: Improve Routing with Time Flow Tables

The previous routing is not ideal for optical DCNs because flow tables are not time-aware.
Since an optical DCN operates with a **time-sliced topology**, the forwarding tables must also take **time** into account.

Therefore, OpenOptics provides time flow table:
```
+------------------------------------- ------------------------------------+
|            Match Fields              ||        Action (forward)          |
+--------------------------------------||----------------------------------+
|  Destination   | Arrival Time Slice  ||   Send Port  |  Send Time Slice  |
+--------------------------------------------------------------------------+
```

Compared to the previous flow table, a time flow table has two additional fields:

**Arrival Time Slice**: The time slice at which the packet arrives at the switch.

**Send Time Slice**: The time slice at which the packet should be transmitted from the switch.


## Define Time Flow Table Entries in OpenOptics

In OpenOptics, time flow table entry can be defined as:

```python
TimeFlowEntry(dst=1, arrival_ts=0, hops=TimeFlowHop(send_port=0, send_ts=1))
```

This means that packets destined for node 1 that arrive at the ToR at time slice 0 should be forwarded out of port 0 at time slice 1.

```{note}
To enforce the such a time flow table, the underlying switch implementation should support buffering
packet until a specified time slice.
The switch implementation for the Mininet backend is a P4 software switch, [bmv2](https://github.com/p4lang/behavioral-model).
OpenOptics is bundled with a modified version of bmv2 that supports time-based buffering.
```

## Your Tasks

You will improve the routing in your optical DCN:

1. Add time flow table entries for nodes 0 and 1 to enable routing between `h0` and `h1`.
2. Verify that in the `ping` test, no packet loss or reordering occurs.

Run the script with:
```python
python3 4-time-flow-table.py
```

Then, in the CLI, test your solution with
```
OpenOptics> h0 ping h1
```