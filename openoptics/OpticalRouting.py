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
import heapq
import networkx as nx
from typing import List, Dict
import queue
import copy
import logging

from openoptics.TimeFlowTable import Path, Step

# Tool funcs


def find_send_port(topo: nx.Graph, src, dst): # To-do: move to OpticalTopo
    """
    Helper function to find the send port given the src and dst nodes in the topo.

    Args:
        topo: Network topology graph
        src: Source node
        dst: Destination node

    Returns:
        The send port of src
    """
    if not topo.has_edge(src, dst):
        return None
    return topo[src][dst].get("port1")

def find_direct_path(
    slice_to_topo: Dict[int, nx.Graph], node1: int, node2: int
) -> List[Path]:
    """
    Helper function to find the direct paths between two nodes for all time slices.
    Can be used by direct routing and VLB.

    Args:
        slice_to_topo: Dictionary mapping time slices to topology graphs
        node1: Source node
        node2: Destination node

    Returns:
        List of paths between the two nodes
    """

    if node1 == node2:
        print("src and dst must be different.")
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

    all_feasible_paths = []

    nb_ts = len(slice_to_topo.keys())
    #dst_arrival_ts = nb_ts - 1 # To-do: find paths from different dst_arrival_ts

    for dst_arrival_ts in range(nb_ts):

        paths = []

        path_buffer = queue.Queue()
        path_buffer.put(
            Path(
                src=src,
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
                #print(f"Find shortest_path {shortest_path}")
                cur_path.arrival_ts = cur_search_ts - 1

                if len(shortest_path) - 1 + len(cur_path.steps) - 1 <= max_hop:
                    # We have found a path

                    found_path = copy.deepcopy(cur_path)
                    found_path.arrival_ts = cur_search_ts
                    shortest_path.reverse() # dst, ..., src
                    for next_node, cur_node in zip(shortest_path[:-1], shortest_path[1:]):
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

                    #print(f"Find a path! {found_path}")
                    paths.append(found_path)
                    continue # When we find a valid path, we don't need to continue search
                else:
                    logger.debug(f"The shortest path reach the max hop {max_hop}.")

            except nx.NetworkXNoPath:
                logger.debug(
                    f"No path found for slice{cur_search_ts} between node{src} and node{cur_node}!"
                )

            # The packet hop-off on this node and wait for one time slice.
            hop_off_path = copy.deepcopy(cur_path)
            hop_off_path.arrival_ts = (cur_search_ts - 1 + nb_ts) % nb_ts
            if hop_off_path.arrival_ts != dst_arrival_ts:
                # print(f"Add wait path {cross_slice_path}")
                path_buffer.put(hop_off_path)
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
                    if neighbor != dst or neighbor not in [
                        step.cur_node for step in cur_path.steps
                    ]:  # Skip visited nodes to avoid loop
                        candidate_path = copy.deepcopy(cur_path)
                        candidate_path.steps.insert(
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
                        # print(f"Add neighbor {neighbor}. New path: {candidate_path}")
                        path_buffer.put(candidate_path)
                    else:
                        logger.debug(
                            f"Node {neighbor} has been visited in the path {cur_path}Skip."
                        )
        if len(paths) == 0:
            raise Exception(f"No path found between node{src} and node{dst}")
    
        paths = list(dict.fromkeys(paths))
        #print(f"Paths from {src} to {dst}: {paths}")
        # paths we get have discrete arrival time slice, we need to generate paths for all time slice
        all_feasible_paths.extend(paths) # Remove multi-path

    #print(f"All feasible paths: {all_feasible_paths}")
    optimal_paths = remove_suboptimal_paths(all_feasible_paths, nb_ts)
    #print(f"{optimal_paths=}")
    paths_for_all_arrival_time_slices = extend_paths_to_all_time_slice(optimal_paths, nb_ts)
    #print(f"Paths for all available time slices: {paths_for_all_arrival_time_slices}")
    return paths_for_all_arrival_time_slices

def remove_suboptimal_paths(paths: List[Path], nb_ts: int):
    """
    Remove suboptimal paths for given a feasiable paths from a src to a dst.
    First, for each arrival_ts, keep only the Path whose last step has the earliest send_ts.
    Second, removed path A if A's arrival ts < B's arrival ts, and A's last send ts < B's send ts. 

    Args:
        paths: A list of paths with the same src and dst
        nb_ts: Number of total time slices

    Returns:
        A list of paths with suboptimal paths removed
    """

    assert [path.src == paths[0].src for path in paths], "Src node of all paths must be the same"
    assert [path.dst == paths[0].dst for path in paths], "Dst node of all paths must be the same"


    earliest_paths: Dict[int, Path] = {}
    for path in paths:
        if path.arrival_ts not in earliest_paths.keys():
            earliest_paths[path.arrival_ts] = path
        else:
            start_ts = path.arrival_ts
            old_ts = earliest_paths[path.arrival_ts].steps[-1].send_ts
            old_path_duration = (old_ts + nb_ts - start_ts) % nb_ts
            new_ts = path.steps[-1].send_ts
            new_path_duration = (new_ts + nb_ts - start_ts) % nb_ts
            if old_path_duration > new_path_duration:
                earliest_paths[path.arrival_ts] = path
            elif old_path_duration == new_path_duration:
                # If path duration is the same, choose the path with less hops
                if len(earliest_paths[path.arrival_ts].steps) > len(path.steps):
                    earliest_paths[path.arrival_ts] = path
    
    return list(earliest_paths.values())


def extend_paths_to_all_time_slice(paths: List[Path], nb_ts: int):
    """
    Helper function used by opera and hoho routing. These routings do not provide
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


def _dijkstra_to_dst(slice_to_topo: Dict[int, nx.Graph], dst, max_hop):
    """
    Backward Dijkstra on the time-expanded schedule graph, from a fixed
    destination.  For every ``(src_tor, cur_slice)`` state it finds the
    shortest-wait forwarding plan to ``dst`` using at most ``max_hop``
    transmit edges, with full optimal substructure: if a packet at
    ``(T, C)`` is on the shortest path to ``dst`` and the next state is
    ``(T', C)``, then ``(T', C)``'s own stored plan is the matching subpath.

    Time-expanded graph
    -------------------
    States: ``(T, C, h)`` where T is a tor, C is a cur_slice, and h is
    the number of transmit edges still available (0 ≤ h ≤ max_hop).
    Forward edges:

      * wait:      ``(T, C, h) -> (T, (C+1) % nb_ts, h)`` with cost 1
      * transmit:  ``(T, C, h) -> (T', C, h-1)`` with cost 0, iff
                    ``slice_to_topo[C]`` has an edge (T, T') and h > 0

    Goal states: any ``(dst, *, *)``.

    Returns
    -------
    parent : dict
        ``state -> (next_state, edge_type, port_or_None)``.  For each
        non-goal state this points at the first forward edge along the
        shortest path.  ``edge_type`` is ``"wait"`` or ``"tx"``; ``port``
        is only set for transmit edges.  Goal states map to ``None``.
    dist : dict
        ``state -> shortest forward duration to dst`` (in slices).
    """
    nb_ts = len(slice_to_topo)
    any_topo = next(iter(slice_to_topo.values()))
    nodes = set(any_topo.nodes())
    is_directed = any_topo.is_directed() if hasattr(any_topo, "is_directed") else False

    INF = float("inf")
    dist: Dict[tuple, float] = {}
    parent: Dict[tuple, tuple] = {}
    pq: List[tuple] = []

    # Initial goal states: already at dst, any slice, any hop budget.
    for c in range(nb_ts):
        for h in range(max_hop + 1):
            state = (dst, c, h)
            dist[state] = 0
            parent[state] = None
            heapq.heappush(pq, (0, state))

    while pq:
        d, state = heapq.heappop(pq)
        if d > dist.get(state, INF):
            continue
        T, C, h = state

        # Relax reverse-wait: forward (T, (C-1) % nb_ts, h) --wait--> (T, C, h)
        prev_C = (C - 1 + nb_ts) % nb_ts
        ns = (T, prev_C, h)
        nd = d + 1
        if nd < dist.get(ns, INF):
            dist[ns] = nd
            parent[ns] = (state, "wait", None)
            heapq.heappush(pq, (nd, ns))

        # Relax reverse-transmit: forward (T', C, h+1) --tx--> (T, C, h)
        # iff edge (T', T) exists at slot C.  The forward transmit from
        # (T', C, h+1) uses one hop, so only allow it if h + 1 <= max_hop.
        if h < max_hop:
            slot_topo = slice_to_topo[C]
            if is_directed:
                candidates = slot_topo.predecessors(T)
            else:
                candidates = slot_topo.neighbors(T)
            for T_prime in candidates:
                if T_prime == T:
                    continue
                port = find_send_port(slot_topo, T_prime, T)
                if port is None:
                    continue
                ns = (T_prime, C, h + 1)
                nd = d  # transmit cost 0
                if nd < dist.get(ns, INF):
                    dist[ns] = nd
                    parent[ns] = (state, "tx", port)
                    heapq.heappush(pq, (nd, ns))

    return parent, dist


def _reconstruct_full_path(parent, start_state):
    """
    Walk the Dijkstra parent chain from ``start_state`` forward to the
    destination, collecting one ``Step`` per transmit edge.  Wait edges
    are implicit in the gap between the starting ``cur_slice`` and each
    transmit's ``send_ts``.

    Returns a list of ``Step`` objects (empty list if ``start_state`` is
    already at the destination, ``None`` if the parent chain is broken —
    which shouldn't happen if ``start_state`` was reachable in the
    Dijkstra relaxation).
    """
    steps: List[Step] = []
    cur = start_state
    # A bounded walk guards against pathological cycles; in practice each
    # wait strictly advances cur_slice and each tx strictly decrements the
    # remaining-hop budget, so the walk terminates in O(nb_ts + max_hop).
    for _ in range(1024):
        entry = parent.get(cur)
        if entry is None:
            # Reached a goal state (we're at dst).
            return steps
        next_state, edge_type, port = entry
        if edge_type == "tx":
            T, C, _h = cur
            next_T, _next_C, _next_h = next_state
            steps.append(
                Step(
                    cur_node=T,
                    step_type="port",
                    send_port=port,
                    send_ts=C,
                    send_node=next_T,
                )
            )
        # "wait" edges advance cur without emitting a step.
        cur = next_state
    return None


def routing_hoho(slice_to_topo: Dict[int, nx.Graph], max_hop) -> list:
    """
    HoHo routing — shortest-path forwarding over the time-expanded
    schedule graph.

    For every ``(src, cur_slice, dst)`` the emitted path represents the
    minimum-duration forwarding plan from ``(src, cur_slice)`` to ``dst``,
    using up to ``max_hop`` transmit edges (additional waits are free).
    By construction the generated paths have optimal substructure: if a
    packet's plan from ``(src, cs)`` to ``dst`` goes through intermediate
    ``(inter, cs')``, then ``inter``'s stored plan at ``cs'`` for the
    same ``dst`` is the matching subpath.  This property is what makes
    ``routing_mode="Per-hop"`` forwarding loop-free even when the table
    lookup has no source-awareness.

    Args:
        slice_to_topo: Topology for each time slice
        max_hop: Maximum number of transmit hops along any path

    Returns:
        A list of ``Path`` objects.  Each path's ``steps`` contains one
        ``Step`` per transmit hop (``path2entries`` trims to the first
        step for Per-hop routing and keeps all steps for Source routing).
    """
    nb_ts = len(slice_to_topo)
    any_topo = next(iter(slice_to_topo.values()))
    nodes = sorted(any_topo.nodes())

    paths: List[Path] = []
    for dst in nodes:
        parent, _dist = _dijkstra_to_dst(slice_to_topo, dst, max_hop)
        for src in nodes:
            if src == dst:
                continue
            for cs in range(nb_ts):
                start = (src, cs, max_hop)
                if start not in parent:
                    # Unreachable within max_hop transmits at this (cs).
                    continue
                steps = _reconstruct_full_path(parent, start)
                if not steps:
                    # (src, cs) is trivially the destination — shouldn't happen
                    # because src != dst.
                    continue
                paths.append(
                    Path(src=src, arrival_ts=cs, dst=dst, steps=steps)
                )
    return paths

def routing_vlb(slice_to_topo: Dict[int, nx.Graph], tor_to_ocs_port: List[int],
                random: bool = False) -> List[Path]:
    """
    VLB routing.

    Args:
        slice_to_topo: Topology for each time slice
        tor_to_ocs_port: Port mapping from ToR to OCS
        random: If True, emit all-255 sentinel for the first hop so that the
            data plane picks a random port at runtime (requires Tofino Random<>
            support).  If False (default), use a deterministic port selection
            from tor_to_ocs_port.

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
                send_port = find_send_port(slice_to_topo[ts], node1, node2)
                if send_port is not None: # There is direct connection at this time slice.
                    path = Path(
                        src=node1,
                        arrival_ts=ts,
                        dst=node2,
                        steps=[
                            Step(cur_node=node1,
                                 step_type="port",
                                 send_port=send_port,
                                 send_ts=ts,
                            ),
                        ]
                    )
                else: #There is no direct connection at this time slice. Send to a random node.
                    if random:
                        first_step = Step(
                            cur_node=255,
                            step_type="port",
                            send_port=255,
                            send_ts=255,
                        )
                    else:
                        first_step = Step(
                            cur_node=node1,
                            step_type="port",
                            send_port=tor_to_ocs_port[ts%len(tor_to_ocs_port)],
                            send_ts=ts,
                        )
                    path = Path(
                        src=node1,
                        arrival_ts=ts,
                        dst=node2,
                        steps=[
                            first_step,
                            Step(cur_node=255, step_type="node", send_node=node2),
                        ],
                    )
                paths.append(path)

    return paths


def routing_vlb_all_random(slice_to_topo: Dict[int, nx.Graph], tor_to_ocs_port) -> List[Path]:
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
