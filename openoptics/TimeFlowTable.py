# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

from typing import List


class TimeFlowHop:
    """
    A hop in a time flow entry.

    Attributes:
        cur_node: Current node identifier
        send_port_or_node: Port or node to send packets to
        send_ts: Time slice to send packets
    """

    def __init__(
        self,
        cur_node=None,
        send_port=None,
        send_node=None,
        send_port_or_node=None,
        send_ts=255,
    ):
        """
        Initialize a TimeFlowHop.

        Args:
            cur_node: Current node identifier
            send_port: Port to send packets to
            send_node: Node to send packets to
            send_port_or_node: Port or node to send packets to (alternative parameter)
            send_ts: Time slice to send packets, defaults to 255
        """
        # desired next hop is for source routing to check missing slice
        self.cur_node = cur_node
        if send_port is not None:
            self.send_port_or_node = send_port
        elif send_node is not None:
            self.send_port_or_node = send_node
        else:
            self.send_port_or_node = send_port_or_node

        self.send_ts = send_ts  # if send_ts 255 means this hop is indexed by node.

    def __str__(self):
        """
        String representation of TimeFlowHop.

        Returns:
            str: Formatted string with hop information
        """
        return (
            f"Current node: {self.cur_node} send slice: {self.send_ts} via port {self.send_port_or_node} "
            f"optional next node:{self.send_port_or_node})"
        )

    def __repr__(self):
        """
        Representation of TimeFlowHop for debugging.

        Returns:
            str: String representation of the object
        """
        # Support printing a list of Hops
        return self.__str__()


class TimeFlowEntry:
    """
    An entry in a time flow table.

    Attributes:
        dst: The destination node
        arrival_ts: The arrival time slice
        hops: A list of hops
    """

    def __init__(self, dst, arrival_ts=None, hops: List[TimeFlowHop] = None):
        """
        Initialize a TimeFlowEntry.

        Args:
            dst: The destination node
            arrival_ts: The arrival time slice
            hops: A list of TimeFlowHop objects
        """
        # desired node is for source routing to check missing slice
        self.dst = dst
        self.arrival_ts = arrival_ts
        self.hops = hops

    def __str__(self):
        """
        String representation of TimeFlowEntry.

        Returns:
            str: Formatted string with entry information
        """
        return (
            f"TimeFlowEntry: dst {self.dst} arrival slice {self.arrival_ts} hops: \n"
            + "".join(f"  hop {i} {hop}" for i, hop in enumerate(self.hops))
        )


class Step:
    """
    One step in a path containing (send time slice && send port) or the node sent to.
    None represents wildcard.

    Attributes:
        cur_node: Current node identifier
        step_type: Type of step ('port' or 'node')
        send_port: Port to send packets through
        send_ts: Time slice to send packets
        send_node: Node to send packets to
    """

    def __init__(
        self,
        cur_node=None,
        step_type="port",
        send_port=None,
        send_ts=None,
        send_node=None,
    ):
        """
        Initialize a Step.

        Args:
            cur_node: Current node identifier
            step_type: Type of step ('port' or 'node')
            send_port: Port to send packets through
            send_ts: Time slice to send packets
            send_node: Node to send packets to

        Raises:
            AssertionError: If step_type is not 'port' or 'node'
        """
        self.cur_node = cur_node
        assert step_type == "port" or step_type == "node", (
            "Only support type 'port' or 'node'"
        )
        self.step_type = step_type

        self.send_port = send_port
        self.send_ts = send_ts
        self.send_node = send_node

    def __str__(self):
        """
        String representation of Step.

        Returns:
            str: Formatted string with step information
        """
        action = f"at {self.send_ts} time slice via port {self.send_port} to next node {self.send_node}\n"
        return (
            f"Current node {self.cur_node if self.cur_node != 255 else '*'}, forwarded by {self.step_type}: "
            + action
        )

    def __repr__(self):
        """
        Representation of Step for debugging.

        Returns:
            str: String representation of the object
        """
        # Support printing a list of Steps
        return self.__str__()


class Path:
    """
    A packet forwarding path.

    Attributes:
        src: Source node
        arrival_ts: Arrival time slice
        dst: Destination node
        steps: List of steps in the path
    """

    def __init__(self, src, arrival_ts, dst, steps: List[Step]):
        """
        Initialize a Path.

        Args:
            src: Source node
            arrival_ts: Arrival time slice
            dst: Destination node
            steps: List of Step objects
        """
        self.src = src
        self.arrival_ts = arrival_ts
        self.dst = dst
        self.steps = steps

    def __str__(self):
        """
        String representation of Path.

        Returns:
            str: Formatted string with path information
        """
        msg = (
            f"\nPath: src:{self.src}, arrive ts:{self.arrival_ts}, dst:{self.dst} steps:\n"
            + "".join(f"  step {i} {step}" for i, step in enumerate(self.steps))
        )
        return msg

    def __repr__(self):
        """
        Representation of Path for debugging.

        Returns:
            str: String representation of the object
        """
        return self.__str__()
