Opera
==================

This example demonstrates how to use OpenOptics library functions to implement Opera [1]_.
You can specify the number of nodes and links per node using the topology function 
:py:meth:`openoptics.OpticalTopo.opera`, and configure routing 
with :py:meth:`openoptics.OpticalRouting.routing_ksp`

.. literalinclude:: ../../../examples/routing_opera.py
   :language: python
   :linenos:
   :caption: examples/routing_opera.py

.. [1] `Expanding across time to deliver bandwidth efficiency and low latency <https://www.usenix.org/conference/nsdi20/presentation/mellette>`_, NSDI'20,