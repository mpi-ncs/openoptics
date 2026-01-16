# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

from typing import List, Union

# Time flow table related classes:
# TimeFlowHop: A hop in a time flow entry.
# TimeFlowEntry: An entry in a time flow table.

class TimeFlowHop:
    """
    A hop in a time flow entry.

    Attributes:
        cur_node: Current node id, for the purpose of checking if the current node is where the packet is supposed to be sent to.
            If not specified, do not perform the check.
        send_port: Port to send packets to. Default to None, meaning send to a random port.
        send_node: Node to send packets to, only valid if send_port is None. Default to None, meaning send to a random node.
        send_port_or_node: Port or node to send packets to.
        send_ts: Time slice to send packets
    """

    def __init__(
        self,
        cur_node=None,
        send_port=None,
        send_node=None,
        send_ts=None,
    ):
        """
        Initialize a TimeFlowHop.

        Args:
            cur_node: Current node id, for the purpose of checking if the current node is where the packet is supposed to be sent to.
                If not specified, do not perform the check.
            send_port: Port to send packets to. Default to None, meaning send to a random port.
            send_node: Node to send packets to, only valid if send_port is None. Default to None, meaning send to a random node.
            send_ts: Time slice to send packets, defaults to None
        """
        # desired next hop is for source routing to check missing slice
        if cur_node is None:
            self.cur_node = 255 # Do not perform checking if the packet is delivered to the desired node.
        else:
            self.cur_node = cur_node
        if send_port is not None:
            self.send_port_or_node = send_port
            self.send_ts = send_ts
        elif send_node is not None:
            self.send_port_or_node = send_node
            self.send_ts = 255 # if send_ts is 255 means this hop is indexed by node.
        else:
            raise ValueError("Must specify either send_port or send_node")

    def __str__(self):
        """
        String representation of TimeFlowHop.

        Returns:
            str: Formatted string with hop information
        """
        if self.send_ts == 255: # send to a specific node
            return (
                f"Current node: {self.cur_node} send to next node {self.send_port_or_node} "
            )
        else: # send to a port at a specific time slice
            return (
                f"Current node: {self.cur_node} send slice: {self.send_ts} via port {self.send_port_or_node} "
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
        arrival_ts: The arrival time slice. If not specified, it's wildcard.
        hops: A list of hops
    """

    def __init__(self, dst, arrival_ts=None, hops: Union[List[TimeFlowHop], TimeFlowHop]= None):
        """
        Initialize a TimeFlowEntry.

        Args:
            dst: The destination node
            arrival_ts: The arrival time slice. If not specified, it's wildcard.
            hops: A list of hops
        """
        # desired node is for source routing to check missing slice
        self.dst = dst
        self.arrival_ts = arrival_ts
        if isinstance(hops, TimeFlowHop):
            self.hops = [hops]
        elif isinstance(hops, list):
            self.hops = hops
        else:
            raise ValueError("hops must be a TimeFlowHop or a list of TimeFlowHop")

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

        if self.step_type == "port": # send to a specific port
            action = f"at {self.send_ts} time slice via port {self.send_port}\n"
        elif self.step_type == "node": # send to a port at a specific node
            action = f"to node {self.send_node}\n"
        else:
            raise ValueError(f"Invalid time flow step type {self.step_type}")
    
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

    def _key(self):
        """
        Compare src, arrival_ts, dst when comparing paths
        """
        return (self.src, self.dst, self.arrival_ts)

    def __eq__(self, other):
        if not isinstance(other, Path):
            return NotImplemented
        return self._key() == other._key()
    
    def __hash__(self):
        return hash(self._key())
    
    def __lt__(self, other):
        if not isinstance(other, Path):
            return NotImplemented
        return self._key() < other._key()