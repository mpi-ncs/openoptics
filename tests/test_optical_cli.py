# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# This software is licensed for non-commercial scientific research purposes only.
# License text: Creative Commons NC BY SA 4.0
#
# Tests for openoptics/OpticalCLI.py
# cmdloop() is patched out so no interactive terminal is needed.

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from helpers import FakeBackend
from openoptics.OpticalCLI import OpticalCLI


# ---------------------------------------------------------------------------
# Helper: build a CLI with all I/O patched out
# ---------------------------------------------------------------------------

def _make_cli(nb_node=4):
    """Return an OpticalCLI wired to a FakeBackend without spawning cmdloop."""
    backend = FakeBackend(nb_node=nb_node)

    mock_net = MagicMock()
    mock_net._backend = backend
    mock_net.device_manager = MagicMock()
    mock_net.time_slice_duration_ms = 128
    mock_net.nb_time_slices = 3
    mock_net.arch_mode = "TO"

    # Stub connect/disconnect so CLI handlers can call them
    mock_net.connect.return_value = True
    mock_net.disconnect.return_value = True

    with patch.object(OpticalCLI, "cmdloop"):
        cli = OpticalCLI(mock_net)

    return cli, mock_net, backend


# ---------------------------------------------------------------------------
# parse_node
# ---------------------------------------------------------------------------

class TestParseNode(unittest.TestCase):

    def setUp(self):
        self.cli, _, _ = _make_cli()

    def test_plain_integer_string(self):
        self.assertEqual(self.cli.parse_node("3"), 3)

    def test_host_prefix(self):
        self.assertEqual(self.cli.parse_node("h0"), 0)
        self.assertEqual(self.cli.parse_node("h7"), 7)

    def test_h_prefix_with_multi_digit(self):
        self.assertEqual(self.cli.parse_node("h12"), 12)

    def test_invalid_string_raises(self):
        with self.assertRaises(ValueError):
            self.cli.parse_node("invalid")

    def test_bare_h_raises(self):
        # "h" alone: s[0]=="h" but s[1:] is "" → int("") raises ValueError
        with self.assertRaises(ValueError):
            self.cli.parse_node("h")


# ---------------------------------------------------------------------------
# get_switches_from_line
# ---------------------------------------------------------------------------

class TestGetSwitchesFromLine(unittest.TestCase):

    def setUp(self):
        self.cli, _, self.backend = _make_cli(nb_node=4)

    def test_empty_line_returns_all_tor_names(self):
        names = self.cli.get_switches_from_line("")
        expected = [sw.name for sw in self.backend.get_tor_switches()]
        self.assertEqual(names, expected)

    def test_specific_name_returned(self):
        names = self.cli.get_switches_from_line("tor0 tor2")
        self.assertIn("tor0", names)
        self.assertIn("tor2", names)
        self.assertNotIn("tor1", names)

    def test_unknown_name_excluded(self):
        names = self.cli.get_switches_from_line("tor0 not_a_switch")
        self.assertNotIn("not_a_switch", names)

    def test_all_valid_names_line(self):
        all_names = "tor0 tor1 tor2 tor3"
        names = self.cli.get_switches_from_line(all_names)
        self.assertEqual(set(names), {"tor0", "tor1", "tor2", "tor3"})


# ---------------------------------------------------------------------------
# do_connect / do_disconnect — argument parsing
# ---------------------------------------------------------------------------

class TestDoConnect(unittest.TestCase):

    def setUp(self):
        self.cli, self.mock_net, _ = _make_cli(nb_node=4)

    def test_two_args_connects_at_ts_0(self):
        self.cli.do_connect("1 2")
        self.mock_net.connect.assert_called_once_with(time_slice=0, node1=1, node2=2)

    def test_three_args_with_explicit_ts(self):
        self.cli.do_connect("1 h0 h3")
        self.mock_net.connect.assert_called_once_with(time_slice=1, node1=0, node2=3)

    def test_five_args_with_ports(self):
        self.cli.do_connect("0 1 2 1 0")
        self.mock_net.connect.assert_called_once_with(
            time_slice=0, node1=1, node2=2, port1=1, port2=0
        )

    def test_wrong_arg_count_prints_error(self):
        # 4 args is invalid; no connect call should happen
        self.cli.do_connect("0 1 2 3")
        self.mock_net.connect.assert_not_called()

    def test_ta_mode_nonzero_ts_skips_connect(self):
        self.mock_net.arch_mode = "TA"
        self.cli.base_network.arch_mode = "TA"
        self.cli.do_connect("1 0 1")   # ts=1 is invalid for TA
        self.mock_net.connect.assert_not_called()


class TestDoDisconnect(unittest.TestCase):

    def setUp(self):
        self.cli, self.mock_net, _ = _make_cli(nb_node=4)

    def test_two_args_disconnects_at_ts_0(self):
        self.cli.do_disconnect("0 1")
        self.mock_net.disconnect.assert_called_once_with(time_slice=0, node1=0, node2=1)

    def test_three_args_with_explicit_ts(self):
        self.cli.do_disconnect("2 h1 h3")
        self.mock_net.disconnect.assert_called_once_with(time_slice=2, node1=1, node2=3)

    def test_five_args_with_ports(self):
        self.cli.do_disconnect("0 1 2 1 0")
        self.mock_net.disconnect.assert_called_once_with(
            time_slice=0, node1=1, node2=2, port1=1, port2=0
        )

    def test_wrong_arg_count_prints_error(self):
        self.cli.do_disconnect("1 2 3 4")
        self.mock_net.disconnect.assert_not_called()


# ---------------------------------------------------------------------------
# do_exit / do_EOF
# ---------------------------------------------------------------------------

class TestLifecycleCommands(unittest.TestCase):

    def setUp(self):
        self.cli, _, _ = _make_cli()

    def test_exit_returns_true(self):
        self.assertTrue(self.cli.do_exit(""))

    def test_eof_returns_true(self):
        self.assertTrue(self.cli.do_EOF(""))

    def test_quit_is_alias_for_exit(self):
        # Class-level alias: do_quit and do_exit must be the same function object
        self.assertIs(OpticalCLI.do_quit, OpticalCLI.do_exit)


# ---------------------------------------------------------------------------
# default() — unknown commands forwarded to backend
# ---------------------------------------------------------------------------

class TestDefaultHandler(unittest.TestCase):

    def setUp(self):
        self.cli, self.mock_net, self.backend = _make_cli()

    def test_known_backend_command_handled(self):
        # default_handler returns True → backend handled it
        self.mock_net._backend.default_handler = MagicMock(return_value=True)
        self.cli.default("h0 ping h1")
        self.mock_net._backend.default_handler.assert_called_once_with("h0 ping h1")

    def test_unknown_command_not_handled(self):
        # default_handler returns False → CLI prints unknown command message
        self.mock_net._backend.default_handler = MagicMock(return_value=False)
        # Should not raise; just prints to stdout
        self.cli.default("totally_unknown_cmd")


if __name__ == "__main__":
    unittest.main()
