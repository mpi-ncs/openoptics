# Tutorial 7: Design Topology for Application

In this section, you will design a network topology for a customized distributed application.

The application is deployed on 8 hosts in an 8-ToR (Top-of-Rack switch) network (one host per ToR).
Each host may send traffic to other hosts.
The diagram below shows an example traffic pattern of the application.

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


## Your Task

We will stick to direct routing for this task. Your goal is to design a topology that:

	1.	Has no packet loss.

	2.	Reduces the average message RTT consistently under 50% tail RTT.

	3.	Reduces the maximum message RTT within 10 time slices.


### Notice:

	•	Don't change the application.

	•	Don't change the routing.

	•	Don't change the slice duration.

	•	Don't change the number of links per ToR

In the provided script, you have a balanced round-robin topology deployed.
Please first check the topology it generated on the dashboard. You can implement `my_topology`
by call
`OpticalTopo.round_robin()` to build the topology you want.

Round-robin implementation in `openoptics.OpticalTopo.round_robin`

To run the application and test it in the OpenOptics CLI:

```bash
OpenOptics-> test_task7
```

You will see **PASS** if your topology meets the requirements.

You can also ping individual hosts to check connectivity and delay.