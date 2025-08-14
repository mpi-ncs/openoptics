Source Routing
=========================================

Source routing allows a sender of a data packet to completely specify the route the packet takes through the network.
OpenOptics' :py:meth:`openoptics.TimeFlowTable.TimeFlowEntry` supports source routing as well as per-hop routing.
Users can specify source routing by setting the ``routing_mode="Source`` in :py:meth:`openoptics.Toolbox.BaseNetwork.deploy_routing`.

.. literalinclude:: ../../../examples/routing_hoho_source.py
   :language: python
   :linenos:
   :caption: examples/routing_hoho_source.py