# Tutorial 8: Design Routing for Application

In this task, you are given a topology that does not provide a direct connection between every pair of hosts.
Your goal is to **design a routing** on this topology for the same customized application as in the previous task.

The routing tool available is Source Routing, a scheme that allows the sender of a data packet to explicitly specify the entire path the packet will take through the network.
`openoptics.TimeFlowTable.TimeFlowEntry` supports both source routing and per-hop routing.

To enable source routing, set
```routing_mode="Source```
 in `openoptics.Toolbox.BaseNetwork.deploy_routing`.

## Application Setting (same as Tutorial 7)

        Group A (Hosts 0–3)                    Group B (Hosts 4–7)
        ┌───────────────┐                       ┌───────────────┐
        │   2× traffic  │                       │   2× traffic  │
        │   within A    │                       │   within B    │
        └───────────────┘                       └───────────────┘

            h0 --- h1                              h4 --- h5
             |  X  |                                |  X  |
            h2 --- h3                              h6 --- h7

                   \                                  /
                    \                                /
                     \________ 1× traffic __________/
                            between groups

	•	The applications are divided into two groups.

	•	Group A = hosts 0–3; Group B = hosts 4–7.

	•	Groups have heavier internal communication and lighter external communication.

	•	Intra-group vs. inter-group traffic ratio: 2:1.


## Your Goal

Design a routing scheme for the given topology that:

(1) Has no packets loss

(2) Keeps the average message RTT consistently below half of the topology cycle time.
Example: if there are 8 time slices and each slice lasts 1000 ms,
the target average RTT should be less than 8*1000/2 = 4000 ms.


### Notice

	•	Do not change the application.

	•	Do not change the topology.

	•	Do not change the slice duration.


To test the application on your network, run in the OpenOptics CLI:
```bash
OpenOptics-> test_task8
```

You will see **PASS** if your routing works.

You can also ping individual hosts to check connectivity and delay.