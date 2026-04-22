# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

import sys

from openoptics.backends.base import BackendBase


class DeviceManager:
    """
    OpenOptics DeviceManager. Monitor and configure the network at runtime.
    """

    def __init__(self, backend: BackendBase, tor_ocs_ports, nb_queue, event_publisher=None):
        sys.path.insert(1, "../behavioral-model/targets/tor_switch")
        sys.path.insert(1, "../behavioral-model/tools")
        from tswitch_CLI import TorSwitchAPI
        import runtime_CLI

        self.switches = backend.get_tor_switches()
        self.optical_switches = backend.get_optical_switches()

        self.switch_clients = {}  # ToR switch name -> custom thrift client
        services = TorSwitchAPI.get_thrift_services()

        for sw in self.switches:
            switch_client = runtime_CLI.thrift_connect(
                "localhost", sw.thrift_port, services
            )[0]
            self.switch_clients[sw.name] = switch_client

        # OCS switches: we only need the standard BMv2 runtime client for
        # `bm_counter_read` — hits/misses are scraped from P4 counters.
        self.ocs_standard_clients = {}  # OCS switch name -> Standard client
        std_services = runtime_CLI.RuntimeAPI.get_thrift_services(
            runtime_CLI.PreType.SimplePreLAG
        )
        for sw in self.optical_switches:
            try:
                standard_client = runtime_CLI.thrift_connect(
                    "localhost", sw.thrift_port, std_services
                )[0]
                self.ocs_standard_clients[sw.name] = standard_client
            except Exception:
                # OCS absent / not reachable: skip, get_ocs_metric() returns {} for it.
                pass

        self.tor_ocs_ports = tor_ocs_ports
        self.nb_queue = nb_queue
        self._event_publisher = event_publisher
        self._ocs_counters_warned = False

    def get_device_metric(self) -> dict:
        """
        Get device metric (queue depth, loss rate, latency, ...)

        Return:
            A dict per switch with keys:
              - ``pq_depth``: ``{(port, queue): depth_in_packets}``
              - ``pq_latency``: ``{(port, queue): (mean_us, max_us)}`` — only
                present for (port, queue) pairs that had at least one sample
                in the current window.
              - ``drop_ctr``: aggregate drop counter
        """
        dict_device_metric = {}
        for sw_name, switch_client in self.switch_clients.items():
            try:
                device_metric = switch_client.get_device_metric()
                dict_device_metric[sw_name] = {
                    "pq_depth": {},
                    "pq_latency": {},
                    "drop_ctr": device_metric.drop_ctr,
                }

                for pq_metric in device_metric.port_queue_metrics:
                    key = (pq_metric.port, pq_metric.queue)
                    dict_device_metric[sw_name]["pq_depth"][key] = pq_metric.depth
                    mean = getattr(pq_metric, "latency_us_mean", None)
                    mx = getattr(pq_metric, "latency_us_max", None)
                    # Drop any negative value — the latency fields are i32 and
                    # a negative reading means a pre-fix BMv2 wrote UINT32_MAX
                    # from a PHV-truncated timestamp. Not a real latency.
                    if mean is not None and mx is not None and mean >= 0 and mx >= 0:
                        dict_device_metric[sw_name]["pq_latency"][key] = (int(mean), int(mx))
            except Exception:
                dict_device_metric[sw_name] = {
                    "pq_depth": {}, "pq_latency": {}, "drop_ctr": 0,
                }

        return dict_device_metric

    # Must match the counter names declared in
    # openoptics/backends/mininet/p4src/ocs/ocs.p4; if you rename them there,
    # rebuild ocs.json and update these constants together.
    _OCS_HIT_COUNTER = "MyIngress.ocs_hit_counter"
    _OCS_MISS_COUNTER = "MyIngress.ocs_miss_counter"

    def get_ocs_metric(self) -> dict:
        """
        Scrape OCS schedule hit/miss counters from every optical switch.

        Returns:
            ``{sw_name: {port: (hits, misses)}}``. Every wired OCS ingress port
            is included even with (0, 0) so the dashboard chart renders from
            epoch start; cumulative counters naturally grow once traffic flows.
            A per-switch dict may be empty if the BMv2 target doesn't define
            the counters (old binary / stale ``ocs.json``); this is logged
            once per process so users know to rebuild.
        """
        result: dict = {}
        nb_ports = len(self.tor_ocs_ports) * max(1, len(self.switches))
        for sw_name, std_client in self.ocs_standard_clients.items():
            per_port: dict = {}
            for port in range(nb_ports):
                try:
                    hit = std_client.bm_counter_read(0, self._OCS_HIT_COUNTER, port)
                    miss = std_client.bm_counter_read(0, self._OCS_MISS_COUNTER, port)
                except Exception:
                    if not self._ocs_counters_warned:
                        print(
                            f"[OpenOptics] OCS '{sw_name}' does not expose "
                            f"{self._OCS_HIT_COUNTER!r} / {self._OCS_MISS_COUNTER!r}. "
                            f"Rebuild ocs.json with the current ocs.p4 to enable "
                            f"schedule hit/miss metrics."
                        )
                        self._ocs_counters_warned = True
                    break  # whole switch lacks the counters; stop scanning it
                per_port[port] = (int(hit.packets), int(miss.packets))
            result[sw_name] = per_port
        return result

    def set_active_queue(self, sw_name, active_qid):
        """
        Set the active queue for a specific switch.

        Args:
            sw_name: The name of the switch to configure
            active_qid: The ID of the queue to set as active
        """
        try:
            self.switch_clients[sw_name].set_active_queue(active_qid)
        except Exception:
            return
        if self._event_publisher is not None:
            self._event_publisher.emit(sw_name, active_qid)
