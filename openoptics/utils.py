# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

from typing import List, Dict
import networkx as nx

from openoptics.TimeFlowTable import TimeFlowEntry, TimeFlowHop, Path
from openoptics.OpticalRouting import find_direct_path
from openoptics.backends.base import TableEntry


def path2entries(
    paths: List[Path], routing_mode, arch_mode="TO"
) -> Dict[int, TimeFlowEntry]:
    """
    Convert paths to time flow table entries

    Args:
        paths: A list of paths
        routing_mode: Per-hop or Source. Trim path if Per-hop.
        arch_mode: TA or TO.
            In TA, packets for each dst has a dedicated queue. send_ts in TimeFlowHop is dst.
            In TO, send_ts is actual sending time slice.

    Returns:
        The dictionary of {src_id : entries}
    """
    assert arch_mode == "TO" or arch_mode == "TA", (
        f"Unsupported architecture mode {arch_mode}"
    )

    entries = {}
    for path in paths:
        hops = []
        if routing_mode == "Per-hop":
            path.steps = [path.steps[0]]
        for step in path.steps:
            if step.step_type == "port":
                hops.append(
                    TimeFlowHop(
                        cur_node=step.cur_node,
                        # In TA, packets for each dst has a dedicated queue.
                        send_ts=step.send_ts if arch_mode == "TO" else path.dst,
                        send_port=step.send_port,
                    )
                )
            elif step.step_type == "node":
                assert arch_mode != "TA", (
                    "Forward based on node is not supported for TA architectures"
                )
                hops.append(
                    TimeFlowHop(
                        cur_node=step.cur_node, send_node=step.send_node
                    )
                )
        if path.src not in entries.keys():
            entries[path.src] = []
        entries[path.src].append(
            TimeFlowEntry(dst=path.dst, arrival_ts=path.arrival_ts, hops=hops)
        )
    return entries



def gen_ocs_commands(ocs_schedule_entries) -> List[TableEntry]:
    """
    Generate table entries for OCS (Optical Circuit Switching) scheduling.

    Args:
        ocs_schedule_entries: List of tuples (slice_id, ingress_port, egress_port)

    Returns:
        List of TableEntry objects for the OCS switch.
    """
    entries = [
        TableEntry(
            table="ocs_schedule",
            action="drop",
            match_keys={},
            action_params={},
            is_default_action=True,
        )
    ]
    for slice_id, ingress_port, egress_port in ocs_schedule_entries:
        entries.append(TableEntry(
            table="ocs_schedule",
            action="ocs_forward",
            match_keys={"ingress_port": ingress_port, "slice_id": slice_id},
            action_params={"egress_port": egress_port},
        ))
    return entries


def tor_table_ip_to_dst(ip_to_tor) -> List[TableEntry]:
    """
    Generate table entries mapping IP addresses to ToR (Top of Rack) switch IDs.

    Args:
        ip_to_tor: Dictionary mapping IP addresses to ToR switch IDs

    Returns:
        List of TableEntry objects.
    """
    return [
        TableEntry(
            table="ip_to_dst_node",
            action="write_dst",
            match_keys={"ip": ip},
            action_params={"dst_node": tor_id},
        )
        for ip, tor_id in ip_to_tor.items()
    ]


def tor_table_arrive_at_dst(tor_id, to_host_port) -> List[TableEntry]:
    """
    Generate table entries for checking if a packet arrives at the dst ToR.
    If so, send it to the host.

    Args:
        tor_id: ID of the ToR switch
        to_host_port: Port number connected to host

    Returns:
        List of TableEntry objects.
    """
    return [
        TableEntry(
            table="arrive_at_dst",
            action="send_to_host",
            match_keys={"tor_id": tor_id},
            action_params={"host_port": to_host_port},
        )
    ]


def tor_table_verify_desired_node(tor_id) -> List[TableEntry]:
    """
    Generate table entries for checking if the receiver is the dst node.

    Args:
        tor_id: ID of the ToR switch

    Returns:
        List of TableEntry objects (two entries: one for tor_id, one wildcard 255).
    """
    return [
        TableEntry(
            table="verify_desired_node",
            action="NoAction",
            match_keys={"tor_id": tor_id},
            action_params={},
        ),
        TableEntry(
            table="verify_desired_node",
            action="NoAction",
            match_keys={"tor_id": 255},
            action_params={},
        ),
    ]


def tor_table_cal_port_slice_to_node(
    tor_id: int, slice_to_topo: Dict[int, nx.Graph]
) -> List[TableEntry]:
    """
    Generate table entries for (src, next_node, send_slice)->send_port.

    Args:
        tor_id: ID of the ToR switch
        slice_to_topo: Dictionary mapping time slices to network topology graphs

    Returns:
        List of TableEntry objects.
    """
    result = []

    if 0 not in slice_to_topo.keys():
        return result

    for dst in slice_to_topo[0].nodes():
        if tor_id == dst:
            continue

        paths = find_direct_path(slice_to_topo, node1=tor_id, node2=dst)
        entries = path2entries(paths, routing_mode="Per-hop")

        if tor_id not in entries.keys():
            continue

        for entry in entries[tor_id]:
            arrival_ts = entry.arrival_ts
            send_ts = entry.hops[0].send_ts
            send_port = entry.hops[0].send_port_or_node
            result.append(TableEntry(
                table="cal_port_slice_to_node",
                action="to_calendar_q_table_action",
                match_keys={"dst": dst, "arrival_ts": arrival_ts},
                action_params={"send_port": send_port, "send_ts": send_ts},
            ))

    return result


def tor_table_routing_source(entry: TimeFlowEntry, nb_time_slices=None) -> List[TableEntry]:
    """
    Generate table entries for source routing.

    Args:
        entry: TimeFlowEntry object containing routing information
        nb_time_slices: Number of time slices. Required when arrival_ts is None
            (wildcard), to generate one entry per time slice.

    Returns:
        List of TableEntry objects.
        action_params["hops"] is a list of (cur_node, send_ts, send_port) tuples.
    """
    hop_count = len(entry.hops)
    action = f"write_ssrr_header_{hop_count - 1}"

    if entry.arrival_ts is None:
        return [
            TableEntry(
                table="add_source_routing_entries",
                action=action,
                match_keys={"dst": entry.dst, "arrival_ts": arrival_ts},
                action_params={"hops": [
                    (hop.cur_node, arrival_ts, hop.send_port_or_node)
                    for hop in entry.hops
                ]},
            )
            for arrival_ts in range(nb_time_slices)
        ]
    else:
        return [
            TableEntry(
                table="add_source_routing_entries",
                action=action,
                match_keys={"dst": entry.dst, "arrival_ts": entry.arrival_ts},
                action_params={"hops": [
                    (hop.cur_node, hop.send_ts, hop.send_port_or_node)
                    for hop in entry.hops
                ]},
            )
        ]


def tor_table_routing_per_hop(entry: TimeFlowEntry, nb_time_slices=None) -> List[TableEntry]:
    """
    Generate table entries for per-hop routing.

    Args:
        entry: TimeFlowEntry object containing routing information
        nb_time_slices: Number of time slices. Required when arrival_ts is None
            (wildcard), to generate one entry per time slice.

    Returns:
        List of TableEntry objects.
    """
    if len(entry.hops) != 1:
        print(
            f"Warning: Find multi-hop time flow entry ({entry}) in Per-hop forwarding mode. Trim following hops."
        )
    hop = entry.hops[0]

    if entry.arrival_ts is None:
        # Wildcard arrival_ts: generate one entry per time slice.
        # Both match key and send_ts action param use the same loop variable.
        return [
            TableEntry(
                table="per_hop_routing",
                action="write_time_flow_entry",
                match_keys={"dst": entry.dst, "arrival_ts": arrival_ts},
                action_params={
                    "cur_node": hop.cur_node,
                    "send_ts": arrival_ts,
                    "send_port": hop.send_port_or_node,
                },
            )
            for arrival_ts in range(nb_time_slices)
        ]
    else:
        return [
            TableEntry(
                table="per_hop_routing",
                action="write_time_flow_entry",
                match_keys={"dst": entry.dst, "arrival_ts": entry.arrival_ts},
                action_params={
                    "cur_node": hop.cur_node,
                    "send_ts": hop.send_ts,
                    "send_port": hop.send_port_or_node,
                },
            )
        ]


def gen_tor_commands(tor_id, slices, port_to_ip, num_hosts, offset):
    """
    Old implementation of loading direct routing table entries.

    Args:
        tor_id: ID of the ToR switch
        slices: List of time slices
        port_to_ip: Mapping of ports to IP addresses
        num_hosts: Number of hosts
        offset: IP address offset

    Returns:
        str: CLI commands for ToR switch configuration
    """
    commands = ""
    # slice_size = int(max_slices / len(slices))
    # commands += f"table_set_default static_config set_static_config {len(slices)} {slice_size} 0 10000 {tor_id}\n"
    # Non-optical network on port 2
    commands += f"table_set_default time_flow_table to_calendar_q {len(slices)} 2\n"
    # For each time slice, register which port is connected to which, and
    # add an entry to the corresponding tor switch's forwarding table
    for send_time_slice, tor_pairs in enumerate(slices):
        connected_port = None
        for tor_pair in tor_pairs:
            if tor_id in tor_pair:
                if tor_id == tor_pair[0]:
                    connected_port = tor_pair[1]
                else:
                    connected_port = tor_pair[0]
                break
        if connected_port is None:
            break
        ips = port_to_ip[connected_port]
        # Optical network on port 1
        for ip in ips:
            arrival_time_slice = 0  # tbf
            commands += f"table_add time_flow_table to_calendar_q {ip} {arrival_time_slice} => {send_time_slice} 1\n"

    for nodes in range(num_hosts):
        for send_time_slice, _ in enumerate(slices):
            commands += f"table_add ocs_schedule ocs_switch 10.0.0.{offset} => {send_time_slice} 0\n"
        offset += 1

    return commands


# Traffic-aware related
def metric_to_matrix(metric: dict) -> dict:
    """Convert queue depth to traffic metric

    Args:
        metric: a dict of {sw_name["pq_depth"] : {(port, queue) : queue depth}}

    Return:
        a dict of traffic matrix {(node1, node2) : traffic}
    """
    traffic_matrix = {}
    for sw_name, metric in metric.items():
        src = int(sw_name[3:])  # tor0
        queue_depth_dict = metric["pq_depth"]
        for (port, queue), depth in queue_depth_dict.items():
            assert port == 0, "Only support single port for now"
            dst = queue  # queue id is the dst id
            traffic_matrix[(src, dst)] = depth
    return traffic_matrix
