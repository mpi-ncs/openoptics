Valiant Load Balancing (VLB)
============================

VLB [1]_ is an oblivious routing scheme that achieves provably optimal load balancing in some settings.
VLB itself and its variants are used in many traffic-oblivious optical DCN architectures, such as RotorNet [2]_, Opera [3]_, and Sirius [4]_.
In vanilla VLB, packets are first routed to an intermediate node selected randomly to achieve load balancing, 
and then forwarded to the final destination node through a direct connection.
You can use the :py:meth:`openoptics.OpticalRouting.routing_vlb` function to configure VLB routing.

.. literalinclude:: ../../../examples/routing_vlb.py
   :language: python
   :linenos:
   :caption: examples/routing_vlb.py

.. [1] `Universal schemes for parallel communication <https://dl.acm.org/doi/abs/10.1145/800076.802479>`_, STOC'81
.. [2] `RotorNet: A Scalable, Low-complexity, Optical Datacenter Network <https://dl.acm.org/doi/abs/10.1145/3098822.3098838>`_, SIGCOMM'17
.. [3] `Expanding across time to deliver bandwidth efficiency and low latency <https://www.usenix.org/conference/nsdi20/presentation/mellette>`_, NSDI'20
.. [4] `Sirius: A Flat Datacenter Network with Nanosecond Optical Switching <https://dl.acm.org/doi/10.1145/3387514.3406221>`_, SIGCOMM'20
