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
                        send_port_or_node=step.send_port,
                    )
                )
            elif step.step_type == "node":
                assert arch_mode != "TA", (
                    "Forward based on node is not supported for TA architectures"
                )
                hops.append(
                    TimeFlowHop(
                        cur_node=step.cur_node, send_port_or_node=step.send_node
                    )
                )
        if path.src not in entries.keys():
            entries[path.src] = []
        entries[path.src].append(
            TimeFlowEntry(dst=path.dst, arrival_ts=path.arrival_ts, hops=hops)
        )
    return entries


def load_table(
    backend,
    switch,
    table_commands,
    cli_path="/behavioral-model/targets/simple_switch/runtime_CLI",
    print_flag=False,
    save_flag=False,
    save_name="saved_commands",
) -> bool:
    """
    Load table entries to a switch via CLI commands

    Args:
        backend: Backend type, currently only supports "Mininet"
        switch: Switch object to load table to
        table_commands: String of CLI commands to execute
        cli_path: Path to the simple_switch CLI executable
        print_flag: Whether to print the command execution result
        save_flag: Whether to save commands to a file
        save_name: Name of file to save commands to (without extension)

    Returns:
        bool: True if successful
    """

    if backend != "Mininet":
        print(f"Unsupported backend {backend}")
        return False

    # print(f"Load table to sw {switch.name} via thrift port {switch.thrift_port}")
    if save_flag == True:
        with open(f"{save_name}.txt", "w") as file:
            file.write(table_commands)

    rst = switch.cmd(
        f'echo "{table_commands}" | {cli_path} --thrift-port {switch.thrift_port}'
    )

    if (rst is not None) and (print_flag == True):
        print(rst)

    if "DUPLICATE_ENTRY" in rst:
        pass
        # print(rst)
        # assert False, "DUPLICATE_ENTRY!"

    return True


def clear_table(
    backend,
    switch,
    table_name,
    cli_path="/behavioral-model/targets/simple_switch/runtime_CLI",
    print_flag=False,
):
    """Clear entries of table in switch

    Args:
        backend: Backend type, currently only supports "Mininet"
        switch: Switch object to clear table from
        table_name: Name of the table to clear
        cli_path: Path to the simple_switch CLI executable
        print_flag: Whether to print the command execution result

    Returns:
        None
    """

    assert backend == "Mininet"
    # print(f"Clear table {table_name} in sw {switch.name} via thrift port {switch.thrift_port}")

    rst = switch.cmd(
        f'echo "table_clear {table_name}" | {cli_path} --thrift-port {switch.thrift_port}'
    )
    # print(rst)

    # rst = switch.cmd(f"echo \"table_dump {table_name}\" | {cli_path} --thrift-port {switch.thrift_port}")
    # print(f"table_dump: {rst}")

    return


def gen_ocs_commands(ocs_schedule_entries):
    """
    Generate CLI commands for OCS (Optical Circuit Switching) scheduling

    Args:
        ocs_schedule_entries: List of tuples (slice_id, ingress_port, egress_port)

    Returns:
        str: CLI commands for OCS scheduling
    """
    # timestamp to time slice
    commands = ""

    # ocs forwarding
    commands += "table_set_default ocs_schedule drop\n"
    for slice_id, ingress_port, egress_port in ocs_schedule_entries:
        commands += f"table_add ocs_schedule ocs_forward {ingress_port} {slice_id} => {egress_port}\n"
        # One direction of link has one entry, so we don't need to add both direction entries here.
        # commands += f"table_add ocs_schedule ocs_forward {egress_port} {slice_id} => {ingress_port}\n"
    return commands


def tor_table_ip_to_dst(ip_to_tor):
    """
    Generate table entries mapping IP addresses to ToR (Top of Rack) switch IDs

    Args:
        ip_to_tor: Dictionary mapping IP addresses to ToR switch IDs

    Returns:
        str: CLI commands for IP to ToR mapping
    """
    commands = ""
    for ip, tor_id in ip_to_tor.items():
        commands += f"table_add ip_to_dst_node write_dst {ip} => {tor_id}\n"

    return commands


def tor_table_arrive_at_dst(tor_id, to_host_port) -> str:
    """
    Generate table entries for check if the packet arrives at the dst ToR. If so, send pkt to host

    Args:
        tor_id: ID of the ToR switch
        to_host_port: Port number connected to host

    Returns:
        A string of commands
    """

    return f"table_add arrive_at_dst send_to_host {tor_id} => {to_host_port}\n"


def tor_table_verify_desired_node(tor_id) -> str:
    """
    Generate table entries for checking if the receiver is the dst node, send pkt to host

    Args:
        tor_id: ID of the ToR switch

    Returns:
        A string of commands
    """
    return (
        f"table_add verify_desired_node NoAction {tor_id} => \n"
        + "table_add verify_desired_node NoAction 255 => \n"
    )


def tor_table_cal_port_slice_to_node(
    tor_id: int, slice_to_topo: Dict[int, nx.Graph]
) -> str:
    """
    Generate table entries for (src, next_node, send_slice)->send_port

    Args:
        tor_id: ID of the ToR switch
        slice_to_topo: Dictionary mapping time slices to network topology graphs

    Returns:
        A string of commands
    """
    commands = ""

    if 0 not in slice_to_topo.keys():
        # topology is empty
        return "\n"

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
            commands += f"table_add cal_port_slice_to_node to_calendar_q_table_action {dst} {arrival_ts} => {send_port} {send_ts}\n"

    return commands


def tor_table_routing_source(entry: TimeFlowEntry):
    """
    Generate table entries for source routing

    Args:
        entry: TimeFlowEntry object containing routing information

    Returns:
        str: CLI commands for source routing entries
    """

    hop_count = len(entry.hops)
    return (
        f"table_add add_source_routing_entries write_ssrr_header_{hop_count - 1} "
        f"{entry.dst} {entry.arrival_ts} => "
        f"{' '.join(f'{hop.cur_node} {hop.send_ts} {hop.send_port_or_node}' for hop in entry.hops)} \n"
    )


def tor_table_routing_per_hop(entry: TimeFlowEntry):
    """
    Generate table entries for per-hop routing

    Args:
        entry: TimeFlowEntry object containing routing information

    Returns:
        str: CLI commands for per-hop routing entries
    """

    if len(entry.hops) != 1:
        print(
            f"Warning: Find multi-hop time flow entry ({entry}) in Per-hop forwarding mode. Trim following hops."
        )
    hop = entry.hops[0]
    return (
        f"table_add per_hop_routing write_time_flow_entry "
        f"{entry.dst} {entry.arrival_ts} => "
        f"{hop.cur_node} {hop.send_ts} {hop.send_port_or_node}\n"
    )


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
