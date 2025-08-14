BaseNetwork
==========================

.. currentmodule:: openoptics.Toolbox

.. automodule:: openoptics.Toolbox.BaseNetwork
.. automethod:: openoptics.Toolbox.BaseNetwork.__init__

User APIs
-----------------

.. autosummary::
   :toctree: generated/

   connect
   disconnect
   add_time_flow_entry
   deploy_topo
   deploy_routing
   start
   start_traffic_aware
   activate_calendar_queue
   pause_calendar_queue
   get_topo

..
   Internal APIs
   -----------------

   .. autosummary::
      :toctree: generated/

      create_nodes
      setup_ocs
      setup_nodes
      start_cli
      start_monitor
      stop_network
      cal_node_port_to_ocs_port