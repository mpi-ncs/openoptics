Routing Primitive
========================================================================

From the previous example, we already have a 3-slice topology consisting of 4 nodes.
This example demonstrates how to add time-flow entries to switches to enable network routing.
For simplicity, we implement direct routing by adding time-flow entries only to nodes 0 and 1.
The detailed definition of the time-flow entry can be found in the :doc:`../../apis/timeflowtable`.


.. literalinclude:: ../../../examples/routing_add_entry.py
   :language: python
   :linenos:
   :caption: examples/routing_add_entry.py