Direct Routing
=========================================

This example demonstrates a direct per-hop routing implementation in a time-sliced optical network. 
The per-hop routing approach configures each switch node to make independent forwarding decisions based 
on the destination address, enabling packets to traverse the network hop-by-hop until they reach their 
final destination. This method provides a straightforward routing mechanism where each intermediate 
node determines the next hop based on local routing information.

.. literalinclude:: ../../../examples/routing_direct_perhop.py
   :language: python
   :linenos:
   :caption: examples/routing_direct_perhop.py