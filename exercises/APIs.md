.  
├── examples/              Example scripts using low- to high-level APIs  
├── exercises/             Hands-on exercises for the tutorial  
├── openoptics/            Core OpenOptics logic and APIs  
│   ├── Toolbox.py         Top-level classes and API entry points  
│   ├── OpticalTopo.py     Functions for topology algorithms  
│   ├── OpticalRouting.py  Routing algorithms and utilities  
├── p4/                    P4 programs for ToR and OCS dataplane behavior  
├── target/                bmv4 software switch implementation with OpenOptics extensions  
│                            (e.g., calendar queue, monitoring tools)  
├── tests/                 Sorry what?


`connect(self, node1, port1, node2, port2, time_slice) -> bool:`
Connect two node ports at the given time slice by configuring OCS,  
if no optical connections haven't been built for both ports.

`deploy_topo(Optional : ciruits)`
Convert the pre-defined circuits to OCS schedules  
Call after calling connect() or given ciruits (from topology functions in OpticalTopo.py)

`add_time_flow_entry(node_id, entries, routing_mode="Per-hop" or "Source")`

`deploy_routing(Optional : paths, routing_mode="Per-hop" or "Source")`