Fastest Path Routing
=========================================

This example demonstrates how to use OpenOptics library functions to implement URO [1]_/HOHO [2]_.
URO routes packets through the fastest path on arbitary topologies.
You can configure HOHO routing with :py:meth:`openoptics.OpticalRouting.routing_hoho`.

.. literalinclude:: ../../../examples/routing_hoho_per_hop.py
   :language: python
   :linenos:
   :caption: examples/routing_hoho.py

.. [1] `Unlocking Diversity of Fast-Switched Optical Data Center Networks With Unified Routing <https://ieeexplore.ieee.org/abstract/document/11119637>`_, IEEE Transactions on Networking, 2025
.. [2] `Hop-On Hop-Off Routing: A Fast Tour across the Optical Data Center Network for Latency-Sensitive Flows <https://dl.acm.org/doi/abs/10.1145/3542637.3542647>`_, APNet'22