# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

import json
import networkx as nx
from typing import List, Dict
import queue
import copy
import logging

from openoptics.TimeFlowTable import Path, Step

# Tool funcs


def find_send_port(topo: nx.Graph, src, dst):
    """
    Helper function to find the send port given the src and dst nodes in the topo.

    Args:
        topo: Network topology graph
        src: Source node
        dst: Destination node

    Returns:
        The send port of src
    """
    return topo[src][dst].get("port1")


def find_direct_path(
    slice_to_topo: Dict[int, nx.Graph], node1: int, node2: int
) -> List[Path]:
    """
    Helper function to find the direct path between two nodes.
    Used by direct routing and VLB.

    Args:
        slice_to_topo: Dictionary mapping time slices to topology graphs
        node1: Source node
        node2: Destination node

    Returns:
        List of paths between the two nodes
    """

    if node1 == node2:
        print("src and dst needs to be different.")
        return []

    paths = []
    slices = sorted(slice_to_topo.keys())

    # Find the first direct connection. Construct paths from the next slice.
    start_ts = None
    for ts in slices:
        cur_topo = slice_to_topo[ts]
        if cur_topo.has_edge(node1, node2):
            start_ts = (ts + 1) % len(slices)
    if start_ts is None:
        return []
    search_order = slices[start_ts:] + slices[:start_ts]

    # Save the pending arrival time slice, generate path when a path is found
    arrival_time_slices = []
    for ts in search_order:
        arrival_time_slices.append(ts)
        cur_topo = slice_to_topo[ts]
        if cur_topo.has_edge(node1, node2):
            send_port = find_send_port(cur_topo, node1, node2)
            for arrival_ts in arrival_time_slices:
                paths.append(
                    Path(
                        src=node1,
                        arrival_ts=arrival_ts,
                        dst=node2,
                        steps=[
                            Step(
                                cur_node=node1,
                                send_port=send_port,
                                send_node=node2,
                                send_ts=ts,
                            )
                        ],
                    )
                )
            arrival_time_slices = []

    return paths


def find_n_hop_path_node_pair(slice_to_topo: Dict[int, nx.Graph], src, dst, max_hop):
    """
    Helper function to find the path between src and dst with the max hop of max_hop.
    Used by hoho and ucmp routing.

    Args:
        slice_to_topo: Dictionary mapping time slices to topology graphs
        src: Source node
        dst: Destination node
        max_hop: Maximum number of hops allowed

    Returns:
        List of paths between source and destination with maximum hops constraint
    """

    # Set up logging
    logger = logging.getLogger(__name__)
    """
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    """

    paths = []

    nb_ts = len(slice_to_topo.keys())
    dst_arrival_ts = nb_ts - 1

    path_buffer = queue.Queue()
    path_buffer.put(
        Path(
            src=None,
            arrival_ts=dst_arrival_ts,
            dst=dst,
            steps=[Step(dst, send_ts=dst_arrival_ts)],
        )
    )

    while not path_buffer.empty():
        # print(f"Current queue {[ele for ele in list(path_buffer.queue)]}")

        cur_path = path_buffer.get()
        cur_node = cur_path.steps[0].cur_node
        cur_search_ts = cur_path.arrival_ts

        try:
            shortest_path = nx.shortest_path(
                slice_to_topo[cur_search_ts], source=src, target=cur_node
            )
            # print(f"Find shortest_path {shortest_path}")
            cur_path.arrival_ts = cur_search_ts - 1

            if len(shortest_path) - 1 + len(cur_path.steps) - 1 <= max_hop:
                # We have found a path

                found_path = copy.deepcopy(cur_path)
                found_path.src = src
                found_path.arrival_ts = cur_search_ts
                for cur_node, next_node in zip(shortest_path[:-1], shortest_path[1:]):
                    found_path.steps.insert(
                        0,
                        Step(
                            cur_node=cur_node,
                            send_port=find_send_port(
                                slice_to_topo[cur_search_ts], cur_node, next_node
                            ),
                            send_ts=cur_search_ts,
                            send_node=next_node,
                        ),
                    )

                # Remove the dst hop
                found_path.steps = found_path.steps[:-1]

                # print(f"Find a path! {found_path}")
                paths.append(found_path)
            else:
                logger.debug(f"The shortest path reach the max hop {max_hop}.")

        except nx.NetworkXNoPath:
            logger.debug(
                f"No path found for slice{cur_search_ts} between node{src} and node{cur_node}!"
            )

        # Even if we find valid path, for searching all possible paths, we always ass wait path and search for neighbors
        wait_path = copy.deepcopy(cur_path)
        wait_path.arrival_ts = (cur_search_ts - 1 + nb_ts) % nb_ts
        if wait_path.arrival_ts != dst_arrival_ts:
            # print(f"Add wait path {wait_path}")
            path_buffer.put(wait_path)
        else:
            logger.debug(
                f"Try adding wait path. But have searched over one cycle. Drop path {cur_path}"
            )

        # We haven't found a valid path to src. Add neibours in the path.
        cur_path.arrival_ts = (cur_search_ts - 1 + nb_ts) % nb_ts

        # print(f"No path found at time slice {cur_search_ts}. Add neighbors to the intermidiate paths.")
        if len(cur_path.steps) >= max_hop:
            logger.debug(
                f"Reach max hop {max_hop}. Cannot search neighbors. Drop path {cur_path}"
            )
        elif cur_path.arrival_ts == dst_arrival_ts:
            logger.debug(f"Have searched over one cycle. Drop path {cur_path}")
        else:
            neighbors = slice_to_topo[cur_search_ts].neighbors(cur_node)
            for neighbor in neighbors:
                if neighbor not in [
                    step.cur_node for step in cur_path.steps
                ]:  # Skip visited nodes to avoid loop
                    cur_path = copy.deepcopy(cur_path)
                    cur_path.steps.insert(
                        0,
                        Step(
                            cur_node=neighbor,
                            send_port=find_send_port(
                                slice_to_topo[cur_search_ts], neighbor, cur_node
                            ),
                            send_ts=cur_search_ts,
                            send_node=cur_node,
                        ),
                    )
                    # print(f"Add neighbor {neighbor}. New path: {cur_path}")
                    path_buffer.put(cur_path)
                else:
                    logger.debug(
                        f"Node {neighbor} has been visited in the path {cur_path}. Skip."
                    )

    # print(f"Paths: {paths}")
    # paths we get have discrete arrival time slice, we need to generate paths for all time slice
    extended_paths = extend_paths_to_all_time_slice(paths, nb_ts)
    # print(f"Extended paths: {extended_paths}")
    return extended_paths


def extend_paths_to_all_time_slice(paths: List[Path], nb_ts: int):
    """
    Helper function used by opera and hoho routing. These routing does not provide
    paths for all arrival time slices. This function fills the missing ones by
    letting packets wait for the nearest available path.

    Args:
        paths: A list of paths whose arrive time slices may be not continuous
        nb_ts: Number of total time slices

    Returns:
        The list of paths whose arrive time slices cover all time slices

    Raises:
        AssertionError: If no paths are provided
    """
    assert len(paths) > 0, "No paths to extend"

    extended_paths = []

    # Make sure path is ordered by arrival time slice
    paths.sort(key=lambda path: path.arrival_ts)

    src = paths[-1].src
    dst = paths[-1].dst
    start_ts = paths[-1].arrival_ts
    assert start_ts < nb_ts, f"Invalid time slice {start_ts}"

    # if there is the last path at slice 4, start filling paths from slice 5
    start_ts = (start_ts + 1) % nb_ts
    search_order = list(range(start_ts, nb_ts)) + list(range(start_ts))

    # Start adding paths based on the earliest (closest to time slice 0) path
    cur_path_id = 0

    for ts in search_order:
        if ts != paths[cur_path_id].arrival_ts:
            cur_path = copy.deepcopy(paths[cur_path_id])
            cur_path.arrival_ts = ts
            extended_paths.append(cur_path)
        if ts == paths[cur_path_id].arrival_ts:
            extended_paths.append(paths[cur_path_id])
            cur_path_id += 1

    return extended_paths


def routing_direct(slice_to_topo: Dict[int, nx.Graph]) -> List[Path]:
    """
    Direct routing.

    Args:
        slice_to_topo: Topology for each time slice

    Returns:
        A list of paths for direct routing
    """
    paths = []

    nodes = slice_to_topo[0].nodes()
    for node1 in nodes:
        for node2 in nodes:
            if node1 == node2:
                continue
            paths.extend(find_direct_path(slice_to_topo, node1, node2))

    return paths


def routing_hoho(slice_to_topo: Dict[int, nx.Graph], max_hop) -> list:
    """
    HOHO routing.

    Args:
        slice_to_topo: Topology for each time slice
        max_hop: Maximum number of hops allowed

    Returns:
        A list of paths for hoho routing
    """
    logger = logging.getLogger(__name__)
    logger.debug("HOHO routing is not yet implemented")

    paths = []
    nodes = slice_to_topo[0].nodes()

    # Search path for every dst node
    for dst in nodes:
        for src in nodes:
            if src == dst:
                continue
            paths.extend(find_n_hop_path_node_pair(slice_to_topo, src, dst, max_hop))

    return paths


def routing_vlb(slice_to_topo: Dict[int, nx.Graph], tor_to_ocs_port) -> List[Path]:
    """
    VLB routing.

    Args:
        slice_to_topo: Topology for each time slice
        tor_to_ocs_port: Port mapping from ToR to OCS

    Returns:
        A list of paths for VLB routing
    """
    paths = []
    nodes = slice_to_topo[0].nodes()
    slices = slice_to_topo.keys()

    for node1 in nodes:
        for node2 in nodes:
            if node1 == node2:
                continue
            for ts in slices:
                path = Path(
                    src=node1,
                    arrival_ts=ts,
                    dst=node2,
                    steps=[
                        Step(
                            cur_node=node1,
                            step_type="port",
                            send_port=tor_to_ocs_port[0],
                            send_ts=ts,
                        ),
                        Step(cur_node=255, step_type="node", send_node=node2),
                    ],
                )
                paths.append(path)

    return paths


def routing_ksp(slice_to_topo: Dict[int, nx.Graph]) -> List[Path]:
    """
    Opera routing by searching the shortest path for each time slice.

    Args:
        slice_to_topo: Topology for each time slice

    Returns:
        A list of paths for direct routing
    """
    paths = []
    slices = slice_to_topo.keys()
    nodes = slice_to_topo[0].nodes()

    for node1 in nodes:
        for node2 in nodes:
            if node1 == node2:
                continue
            for ts in slices:
                try:
                    path_nodes = nx.shortest_path(slice_to_topo[ts], node1, node2)
                except nx.NetworkXNoPath:
                    print(
                        f"No path found for slice{ts} between node{node1} and node{node2}!"
                    )
                    continue

                steps = []
                for cur_node, next_node in zip(path_nodes[:-1], path_nodes[1:]):
                    send_port = slice_to_topo[ts][cur_node][next_node].get("port1")
                    steps.append(
                        Step(cur_node=cur_node, send_port=send_port, send_ts=ts)
                    )

                path = Path(src=node1, arrival_ts=ts, dst=node2, steps=steps)
                paths.append(path)
    return paths


def routing_direct_ta(slice_to_topo: Dict[int, nx.Graph]) -> List[Path]:
    """
    Direct routing for traffic-aware.

    Args:
        slice_to_topo: Topology for each time slice

    Returns:
        A list of paths for direct routing

    Raises:
        AssertionError: If more than one time slice is provided
    """
    paths = []

    assert len(slice_to_topo.keys()) == 1, (
        "Only supports TA architecture with single time slice."
    )

    nodes = slice_to_topo[0].nodes()
    for node1 in nodes:
        for node2 in nodes:
            if node1 == node2:
                continue
            # There could be direct path between any nodes.
            # We send pkts to the default port 0.
            # They will be buffered in corresbonding queues.
            paths.append(
                Path(
                    src=node1,
                    arrival_ts=0,
                    dst=node2,
                    steps=[Step(cur_node=node1, send_port=0)],
                )
            )

    return paths


def make_json(tor_id, tor_tb):
    """
    Generate JSON configuration for ToR switch.

    Args:
        tor_id: ToR switch ID
        tor_tb: ToR table entries
    """
    jsons = []
    table_name = f"tor{tor_id % 4}_pipe.Ingress.tb_forwarding_table"
    action = "Ingress.enhqueue.set_send_slice_tor"

    for entry in tor_tb:
        item = {
            "table_name": table_name,
            "action": action,
            "key": {
                "time_slice": entry["time_slice"],
                "dst": entry["dst"],
            },
            "data": {
                "send_slice": entry["send_slice"],
                "next_tor": entry["next_tor"],
            },
        }
        jsons.append(item)

    with open(f"tables/tor{tor_id}.json", "w") as outfile:
        json.dump(jsons, outfile, indent=2)
