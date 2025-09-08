# Tutorial 7: Design Topology for an Application

Programming with low-level APIs can be tedious and error-prone.
The following two tutorials demonstrate how to use OpenOptics' high-level APIs to
build optical DCNs with just a few lines of code.

In this tutorial, you will design a network topology tailored for a custom distributed application.

The application is deployed on 8 hosts in an 8-ToR (Top-of-Rack switch) network, with one host per ToR.
Each host may send traffic to every other host.

The diagram below illustrates the application's traffic pattern:

        Group A (Hosts 0–3)                    Group B (Hosts 4–7)
        ┌───────────────┐                       ┌───────────────┐
        │ dense traffic │                       │ dense traffic │
        │ within group  │                       │ within group  │
        └───────────────┘                       └───────────────┘

            h0 --- h1                              h4 --- h5
             |  X  |                                |  X  |
            h2 --- h3                              h6 --- h7

                   \                                  /
                    \                                /
                     \______ light traffic _________/
                    between nodes in different groups

	•	The applications are divided into two groups.

	•	Group A = hosts 0–3; Group B = hosts 4–7.

	•	Groups have denser intra-group communication and lighter inter-group communication.

	•	Traffic ratio (intra-group : inter-group) = 2:1. (You don’t need to fit the topology perfectly to this ratio.)

By default, the script tutorials/7-topology.py creates a round-robin topology across all nodes (you will modify this topology in the this task):
	•	Each node connects directly to one other node per time slice.
	•	Across all time slices, each node has a direct connection to every other node.

```{note}
Run the script first and inspect the topology on the dashboard to understand the default round-robin schedule.  
Then, modify the input arguments of `round_robin()` to check when topologies are generated.
```

## Your Tasks

We will use direct routing for this task. Your goal is to design a topology that:

1. Ensures **no packet loss**: the schedule must include direct connections between all node pairs.
2. Allocates **more connections within groups** than across groups.
3. **Bonus**: After completing the above, try to reduce the **maximum message RTT** to within 10 time slices, if you haven't.


### Notice:

- Don't change the application.
- Don't change the routing.
- Don't change the slice duration.
- Don't change the number of links per ToR


```{note}
You can complete this task using only `OpticalTopo.round_robin()` inside the topology generator function `my_topology`.
```

To test your design in the OpenOptics CLI:

```bash
OpenOptics-> test_task7
```

You will see **PASS** if your solution satisfies all requirements.

You can also use `ping` between individual hosts to check connectivity and delay.