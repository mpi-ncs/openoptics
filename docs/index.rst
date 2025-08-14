.. OpenOptics documentation master file, created by
   sphinx-quickstart on Thu Jul 31 14:51:27 2025.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

OpenOptics: Democratizing Optical DCNs
============================================================================
..
   .. image:: ../assets/openoptics_words.svg
      :alt: OpenOptics Logo
      :align: center

.. 
   .. centered::

**Easy design, testing, and deployment of optical DCNs for everyone.**

.. note::

   We will hold a tutorial at `SIGCOMM'25 <https://conferences.sigcomm.org/sigcomm/2025/tutorials-hackathons/tutorial-odcn/>`_! Attend to build your own optical DCNs with us!

OpenOptics is a general framework for realizing different optical data center network architectures in a plug-and-play manner.
With OpenOptics, users can deploy customized optical data center networks on the testbed, emulation, or simulation with ~10 lines of Python code.
Under the hood, user configurations are translated into table entries and control plane programs, 
which are then deployed to the underlying optical and P4-programmable switches.

.. code-block:: python

   from openoptics import Toolbox, OpticalTopo, OpticalRouting
   
   nb_node = 8
   net = Toolbox.BaseNetwork(nb_node = nb_node, time_slice_duration_ms = 512, backend="Mininet")
   circuits = OpticalTopo.round_robin(nb_node=nb_node)
   net.deploy_topo(circuits)
   paths = OpticalRouting.routing_direct(net.slice_to_topo)
   net.deploy_routing(paths)
   net.start()

After deployment, users can monitor the network with OpenOptics Dashboard.

.. image:: ../assets/dashboard.png
   :alt: OpenOptics Dashboard

We have now published the Mininet backend, where users can realize optical DCNs in a full software emulation using BMv2 software switches and Mininet networks.
The Tofino-based backend will be released soon.

.. toctree::
   :maxdepth: 1

   quickstart
   installation

   examples/examples
   apis_index
   about
.. 
   tutorial/tutorial_index

..
   Indices and tables
   ==================

   * :ref:`genindex`
   * :ref:`modindex`
   * * :ref:`search`

.. raw:: html

   <a href="https://imprint.mpi-klsb.mpg.de/inf/openoptics.mpi-inf.mpg.de">Imprint</a> / <a href="https://data-protection.mpi-klsb.mpg.de/inf/openoptics.mpi-inf.mpg.de">Data Protection</a>

