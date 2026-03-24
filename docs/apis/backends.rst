Backends
========

The backend abstraction layer allows OpenOptics to run on different network simulators
and hardware targets. The ``create_backend`` factory selects the implementation at
runtime based on the ``backend`` parameter passed to :class:`~openoptics.Toolbox.BaseNetwork`.

.. autofunction:: openoptics.backends.create_backend

.. autoclass:: openoptics.backends.SwitchHandle
   :members:

.. autoclass:: openoptics.backends.BackendBase
   :members:
   :special-members: accepted_kwargs
