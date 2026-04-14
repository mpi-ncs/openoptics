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

   - The OpenOptics `paper <https://ymlei.github.io/assets/OpenOptics_CR.pdf>`_ has been accepted by NSDI'26!

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
   paths = OpticalRouting.routing_direct(net.get_topo())
   net.deploy_routing(paths)
   net.start()

After deployment, users can monitor the network with OpenOptics Dashboard.

.. image:: ../assets/dashboard.png
   :alt: OpenOptics Dashboard

OpenOptics ships with two backends: a Mininet backend that runs optical DCNs
as full software emulations on BMv2 switches, and a Tofino backend that
deploys the same Python code onto real Tofino2 hardware.

.. toctree::
   :maxdepth: 1

   quickstart
   installation
   examples/examples
   tutorials/tutorial_index
   tofino-backend
   apis_index
   about

..
   Indices and tables
   ==================

   * :ref:`genindex`
   * :ref:`modindex`
   * * :ref:`search`

.. raw:: html

   <a href="https://imprint.mpi-klsb.mpg.de/inf/openoptics.mpi-inf.mpg.de">Imprint</a> / <a href="https://data-protection.mpi-klsb.mpg.de/inf/openoptics.mpi-inf.mpg.de">Data Protection</a>

