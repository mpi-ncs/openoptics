# Tutorial 5: Multi-Hop Routing with Time Flow Tables

In the previous task, packets were always sent from the source to the destination through the next available direct connection.
Now we till try something different, **multi-hop routing**, where packets are forwarded through intermediate nodes when a direct path is not immediately available.

Consider the following topology schedule:

![topo](../../assets/example_connect.png)

Suppose `h0` wants to send a packet to `h1` at time slice 1.
With the direct routing you implemented earlier, the packet cannot be transmitted until time slice 0 of the next cycle, when a direct connection between `h0` and `h1` exists.

But with multi-hop routing, the packet can be sent from `h0` to `h2` at time slice 1, and then forwarded from `h2` to `h1` at time slice 2.
This allows earlier delivery by leveraging intermediate nodes.

## Your Tasks

You will implement **multi-hop routing** with time flow tables in your optical DCN:

1. Add time flow table entries to enable routing between `h0` and `h1` (You don't have to add time flow table entries for routing packets between any other node pairs but feel free to do so if you wish).
2. Verify that in the `ping` test, no packet loss occurs.
3. Compare the `ping` RTT with that of direct routing. Is the result what you expected? Why or why not?

Run the script with:
```python
python3 5-multi-hop-routing.py
```

Then, in the CLI, test your solution with
```
OpenOptics> h0 ping h1
```