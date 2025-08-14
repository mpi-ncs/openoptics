# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

import networkx as nx
import matplotlib.pyplot as plt
import math
import numpy as np
import itertools
import random

"""
Circuit:
[time_slice, node1, node2, port1, port2]
"""


def static_topo(nb_node, nb_link=1):
    """
    Static topology generated from a random regular graph.

    Args:
        nb_node: Number of nodes
        nb_link: Number of links

    Returns:
        A list of circuits, with only one time slice,
        of a random regular graph on nodes which is an expander graph with very good probability.
    """

    # g = nx.maybe_regular_expander_graph(n=nb_node, d=nb_link) # 3.6
    g = nx.random_regular_graph(n=nb_node, d=nb_link, seed=1)

    # Figure out which port is used to connect other nodes
    port_id_tracker = [0] * nb_node

    circuits = []

    for edge in g.edges():
        node1, node2 = edge
        port1, port2 = port_id_tracker[node1], port_id_tracker[node2]
        circuits.append([0, node1, node2, port1, port2])

        # Update the next available port.
        port_id_tracker[node1] += 1
        port_id_tracker[node2] += 1

    assert all(port_id == nb_link for port_id in port_id_tracker)

    return circuits


def round_robin(nb_node=None, nodes=None, port1=0, port2=0, self_loop=False) -> list:
    """
    Create a round-robin topology with the circle method. Assume one upper link per node.

    Args:
        nb_node: Number of nodes
        nodes: If not specified, create node list based on the number of nodes.
                Otherwise create round-robin within given nodes.
        port1: The port src node uses to connect. 0 by default
        port2: The port dst node uses to connect. 0 by default
        self_loop: Whether to add loop-back time slice.

    Returns:
        A list of circuits.
    """

    if nodes is None:
        assert nb_node is not None, "Need either nb_node or node"
        nodes = list(range(nb_node))
    else:
        nb_node = len(nodes)
        if isinstance(nodes, np.ndarray):
            nodes = nodes.tolist()

    # assert nb_node % 2 == 0, "Round-robin needs number of nodes to be even."
    if nb_node % 2 == 1:
        nb_node = nb_node + 1
        nodes.append(-1)  # -1 indicate dummy node

    circuits = []

    for slice_id in range(nb_node - 1):
        for i in range(nb_node // 2):
            if nodes[i] == -1 or nodes[-i - 1] == -1:
                # does not connect dummy node
                continue
            circuits.append([slice_id, nodes[i], nodes[-i - 1], port1, port2])
        nodes.insert(1, nodes.pop(-1))

    # Add a loop-back time slice for being the building block of more complex topology
    if self_loop:
        for node_id in range(nb_node):
            circuits.append([nb_node - 1, nodes[node_id], nodes[node_id], port1, port2])

    return circuits


def opera(nb_node, nb_link, nodes=None):
    """
    Opera topology support multiple upper links per node.
    In (nb_node / nb_link) time slices, each link of every node connects (nb_node / nb_link) number of nodes
    We connect ports with the same index together.

    Args:
        nb_node: Number of nodes
        nb_link: Number of links per node
        nodes: List of nodes (optional)

    Returns:
        List of circuits for the opera topology
    """
    # First we generate a basic round robin that each node connects every other node.
    base_circuits = round_robin(nb_node, nodes, self_loop=True)
    # e.g. 4 nodes, 2 links
    # slice0: 0(p0) <-> 3(p0), 1(p0) <-> 2(p0)
    # slice1: 0(p0) <-> 2(p0), 1(p0) <-> 3(p0)
    # slice2: 0(p0) <-> 1(p0), 2(p0) <-> 3(p0)
    # slice3: self loop

    # Randomize topo by shuffling topologies to different time slices
    topo_randomize_ts(base_circuits)

    # To connect all nodes in nb_node / nb_link time slice, we merge time slices, as well as connections,
    # with the ratio of nb_link. The connections in (nb_link) time slices are achieved by nb_link links at one time slice.
    # With two upper links, we map old_ts to new_ts by (2n -> n), (2n+1 -> n)
    # With three upper links, we map old_ts to new_ts by (3n -> n), (3n+1 -> n), (3n+2 -> n)

    merged_circuit = []
    for ts, node1, node2, port1, port2 in base_circuits:
        port_id = ts % nb_link
        merged_circuit.append([ts // nb_link, node1, node2, port_id, port_id])
    # e.g. 4 nodes, 2 links
    # slice0: 0(p0) <-> 3(p0), 0(p1) <-> 2(p1), 1(p0) <-> 2(p0), 1(p1) <-> 3(p1)
    # slice1: 0(p0) <-> 1(p0), 0&1 (p1)   loop, 2(p0) <-> 3(p0), 2&3 (p1)   loop

    offset_circuits = port_offset(merged_circuit)
    # offset_circuits = merged_circuit

    return offset_circuits


def shale(nb_node, h, nodes=None):
    """
    Create a Shale topology.
    We assume num of links == h, so rr in different dimension doesn't influence each other.

    Args:
        nb_node: Number of nodes
        h: Number of dimensions
        nodes: List of nodes (optional)

    Returns:
        List of circuits for the shale topology
    """
    if nodes is None:
        nodes = list(range(nb_node))
    else:
        nb_node = len(nodes)

    root = int(math.pow(nb_node, 1 / h))
    assert root**h == nb_node, "number of nodes need to be the power of h"

    # Reshape nodes into an h-dimensional cube
    nodes = np.array(nodes).reshape([root] * h)

    circuits = []
    for pos in range(h):
        for base_indices in itertools.product(range(root), repeat=h - 1):
            # base indices are (0,0), (0,1), (1,0), (1,1)
            indices = base_indices[:pos] + (slice(None),) + base_indices[pos:]
            # indices are (:,0,0), (:,0,1), (:,1,0), (:,1,1), (0,:,0), (0,:,1), (1,:,0)....
            circuits.extend(round_robin(nodes=nodes[indices], port1=pos, port2=pos))

    return circuits


def bipartite_matching(
    nb_node, nb_link, traffic_matrix: dict, prev_circuits=None
) -> list:
    """
    Create a bipartite matching topology based on traffic matrix.

    Args:
        nb_node: Number of nodes
        nb_link: Number of links
        traffic_matrix: Dictionary with traffic information between nodes

    Returns:
        List of circuits for the bipartite matching topology

    Raises:
        AssertionError: If nb_link is not 1 (only supports one link)
    """
    assert nb_link == 1, "bipartite_matching supports one link only"
    # print(f"metric: {traffic_matrix}", flush=True)

    # If no traffic, keep the previous topology
    # print(traffic_matrix)
    if all(v == 0 for v in traffic_matrix.values()):
        return prev_circuits

    edges = []
    for node1 in range(nb_node):
        for node2 in range(node1 + 1, nb_node):
            # Aggragate weights for bi-directional traffic
            weight_1 = traffic_matrix.get((node1, node2), 0)  # fill 0 if no traffic
            weight_2 = traffic_matrix.get((node2, node1), 0)
            edges.append((node1, node2, weight_1 + weight_2))

    # print(f"metric edges: {edges}")
    g = nx.Graph()
    g.add_weighted_edges_from(edges)

    matching = nx.max_weight_matching(g, maxcardinality=True)

    circuits = []
    for src, dst in matching:
        circuits.append([0, src, dst, 0, 0])

    # print(f"new circuits: {circuits}")
    return circuits


##########################
#    Helper functions    #
##########################
def topo_randomize_ts(circuits: list):
    """
    Randomize connection order (time_slice -> connections mapping) for circuits.

    Args:
        circuits: List of circuits to randomize

    Returns:
        List of randomized circuits
    """
    circuits.sort(key=lambda x: x[4])
    # print(circuits)

    ts_set = set()
    for ts, node1, node2, port1, port2 in circuits:
        ts_set.add(ts)

    time_slices = sorted(list(ts_set))
    shuffled = time_slices.copy()
    random.shuffle(shuffled)

    shuffled_circuits = []
    for ts, node1, node2, port1, port2 in circuits:
        shuffled_circuits.append([shuffled[ts], node1, node2, port1, port2])

    # Sort based on time slice
    shuffled_circuits.sort(key=lambda x: x[0])
    # print(shuffled_circuits)

    return shuffled_circuits


def port_offset(circuits: list):
    """
    Helper function to transform the circuits to reconfigure topology one port per time slice.
    New nb_time_slice = old nb_time_slice * nb_links

    Args:
        circuits: List of circuits to transform

    Returns:
        List of transformed circuits with port offset
    """
    nb_time_slice = get_nb_time_slice_from_circuits(circuits)
    nb_links = get_nb_links_from_circuits(circuits)

    offset_circuits = []
    for ts, node1, node2, port1, port2 in circuits:
        assert port1 == port2, (
            "To enable port offset, port id should be the same for both side."
        )
        new_ts_start = ts * nb_links + port1
        new_ts_end = (ts + 1) * nb_links + port1
        for new_ts in range(new_ts_start, new_ts_end):
            offset_circuits.append(
                [new_ts % (nb_time_slice * nb_links), node1, node2, port1, port2]
            )

    return offset_circuits


def get_nb_time_slice_from_circuits(circuits: list):
    """
    Helper function to get the number of time slices from circuits.

    Args:
        circuits: A list of circuits

    Returns:
        The number of time slices
    """
    max_ts = 0
    for ts, node1, node2, port1, port2 in circuits:
        if ts > max_ts:
            max_ts = ts
    return max_ts + 1


def get_nb_links_from_circuits(circuits: list):
    """
    Helper function to get the number of links from circuits.

    Args:
        circuits: A list of circuits

    Returns:
        The number of links
    """
    max_port = 0
    for ts, node1, node2, port1, port2 in circuits:
        if port1 > max_port:
            max_port = port1
        if port2 > max_port:
            max_port = port2
    return max_port + 1


def draw_topo(slice_to_topo):
    """
    Draw the topology using matplotlib.

    Args:
        slice_to_topo: Dictionary mapping time slices to topology graphs

    Returns:
        matplotlib figure object
    """
    nb_time_slices = len(slice_to_topo)
    pos = nx.circular_layout(sorted(slice_to_topo[0].nodes))
    fig, axs = plt.subplots(1, nb_time_slices)

    if nb_time_slices == 1:
        axs = [axs]

    for time_slice, ax in enumerate(axs):
        nx.draw(
            slice_to_topo[time_slice],
            ax=ax,
            pos=pos,
            with_labels=True,
            node_color="#6A9FB5",
            edge_color="#95A5A6",
            arrowsize=5,
            arrowstyle="->",
            font_color="white",
        )
        ax.tick_params(left=True, bottom=True, labelleft=True, labelbottom=True)
        ax.axis("on")
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(f"time slice={time_slice}")

    fig.set_size_inches(3 * nb_time_slices, 3)
    return fig
