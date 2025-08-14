Traffic Aware Workflow
========================

Unlike traffic-oblivious topologies, traffic-aware architectures dynamically adapt the network topology based on runtime traffic patterns.
This requires a feedback loop to collect traffic information and update the network topology accordingly.
All of this functionality is encapsulated in :py:meth:`openoptics.Toolbox.BaseNetwork.start_traffic_aware`, where users only need to 
specify the topology generation function and the routing algorithm they wish to use.
The configuration workflow is nearly identical to the previous examples of traffic-oblivious architectures.

Try ping between nodes, what do you observe on the dashboard?

.. literalinclude:: ../../../examples/ta.py
   :language: python
   :linenos:
   :caption: examples/ta.py