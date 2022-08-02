#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.


from typing import Any, List, Optional, Sequence

import bunch
import click
from openr.cli.commands import decision
from openr.cli.utils.utils import parse_nodes


class DecisionCli:
    def __init__(self):
        self.decision.add_command(PathCli().path)
        self.decision.add_command(DecisionAdjCli().adj)
        self.decision.add_command(DecisionPrefixesCli().prefixes)
        self.decision.add_command(
            DecisionRoutesComputedCli().routes, name="routes-computed"
        )
        self.decision.add_command(DecisionRibPolicyCli().show, name="rib-policy")
        self.decision.add_command(ReceivedRoutesCli().show)

        # for TG backward compatibility. Deprecated.
        self.decision.add_command(DecisionRoutesComputedCli().routes, name="routes")
        self.decision.add_command(DecisionValidateCli().validate)

    @click.group()
    @click.pass_context
    def decision(self):    # noqa: B902
        """CLI tool to peek into Decision module."""
        pass


class PathCli:
    @click.command()
    @click.option(
        "--src", default="", help="source node, " "default will be the current host"
    )
    @click.option(
        "--dst",
        default="",
        help="destination node or prefix, " "default will be the current host",
    )
    @click.option("--max-hop", default=256, help="max hop count")
    @click.option("--area", default=None, help="area identifier")
    @click.pass_obj
    def path(self, src, dst, max_hop, area):    # noqa: B902
        """path from src to dst"""

        decision.PathCmd(self).run(src, dst, max_hop, area)


class DecisionRoutesComputedCli:
    @click.command()
    @click.option(
        "--nodes",
        default="",
        help="Get routes for a list of nodes. Default will get "
        "host's routes. Get routes for all nodes if 'all' is given.",
    )
    @click.option(
        "--prefixes",
        "-p",
        default="",
        multiple=True,
        help="Get route for specific IPs or Prefixes.",
    )
    @click.option(
        "--labels",
        "-l",
        type=click.INT,
        multiple=True,
        help="Get route for specific labels.",
    )
    @click.option("--json/--no-json", default=False, help="Dump in JSON format")
    @click.pass_obj
    def routes(self, nodes, prefixes, labels, json):    # noqa: B902
        """Request the routing table from Decision module"""

        nodes = parse_nodes(self, nodes)
        decision.DecisionRoutesComputedCmd(self).run(nodes, prefixes, labels, json)


# TODO: Remove in a few months completely ...
class DecisionPrefixesCli:
    @click.command()
    @click.option(
        "--nodes",
        default="",
        help="Dump prefixes for a list of nodes. Default will dump host's "
        "prefixes. Dump prefixes for all nodes if 'all' is given.",
    )
    @click.option("--json/--no-json", default=False, help="Dump in JSON format")
    @click.option("--prefix", "-p", default="", help="Prefix filter. Exact match")
    @click.option(
        "--client-type",
        "-c",
        default="",
        help="Client type filter. Provide name e.g. loopback, bgp",
    )
    @click.pass_obj
    @click.pass_context
    def prefixes(self, cli_opts: Any, nodes: List[str], json: bool, prefix: str, client_type: str) -> None:
        """show the prefixes from Decision module - Deprecated"""

        click.secho(
            "Command deprecated - Please use `breeze decision received-routes`",
            bold=True,
            err=True,
        )
        self.exit(1)


class DecisionAdjCli:
    @click.command()
    @click.option(
        "--nodes",
        default="",
        help="Dump adjacencies for a list of nodes. Default will dump "
        "host's adjs. Dump adjs for all nodes if 'all' is given",
    )
    @click.option(
        "--areas",
        "-a",
        multiple=True,
        default=[],
        help="Dump adjacencies for the given list of areas. Default will dump "
        "adjs for all areas. Multiple areas can be provided by repeatedly using "
        "either of the two valid flags: -a or --areas",
    )
    @click.option("--bidir/--no-bidir", default=True, help="Only bidir adjacencies")
    @click.option("--json/--no-json", default=False, help="Dump in JSON format")
    @click.pass_obj
    def adj(self, nodes, areas, bidir, json):    # noqa: B902
        """dump the link-state adjacencies from Decision module"""

        nodes = parse_nodes(self, nodes)
        decision.DecisionAdjCmd(self).run(nodes, set(areas), bidir, json)


class DecisionValidateCli:
    @click.command()
    @click.option("--json/--no-json", default=False, help="Dump in JSON format")
    @click.argument("areas", nargs=-1)
    @click.pass_obj
    @click.pass_context
    def validate(self, cli_opts: bunch.Bunch, json: bool, areas: Sequence[str]) -> None:
        """
        Check all prefix & adj dbs in Decision against that in KvStore

        TODO: Fix json to be combined for all areas ...
        If --json is provided, returns database diffs in the following format.
        "neighbor_down" is a list of nodes not in the inspected node's dump that were expected,
        "neighbor_up" is a list of unexpected nodes in inspected node's dump,
        "neighbor_update" is a list of expected nodes whose metadata are unexpected.
            {
                "neighbor_down": [
                    {
                        "new_adj": null,
                        "old_adj": $inconsistent_node
                    }
                ],
                "neighbor_up": [
                    {
                        "new_adj": $inconsistent_node
                        "old_adj": null
                    }
                ],
                "neighbor_update": [
                    {
                        "new_adj": $inconsistent_node
                        "old_adj": $inconsistent_node
                    }
                ]
            }
        """

        self.exit(decision.DecisionValidateCmd(cli_opts).run(json, areas))


class DecisionRibPolicyCli:
    @click.command()
    @click.pass_obj
    def show(self):    # noqa: B902
        """
        Show currently configured RibPolicy
        """

        decision.DecisionRibPolicyCmd(self).run()


class ReceivedRoutesCli:
    @click.command("received-routes")
    @click.argument("prefix", nargs=-1, type=str)
    @click.option("--node", help="Filter on node name", type=str)
    @click.option("--area", help="Filter on area name", type=str)
    @click.option(
        "--detail/--no-detail",
        default=False,
        help="Show all details including tags and area-stack",
    )
    @click.option(
        "--tag2name/--no-tag2name",
        default=False,
        help="Translate tag string to human readable name",
    )
    @click.option("--json/--no-json", default=False, help="Output in JSON format")
    @click.pass_obj
    def show(self, prefix: List[str], node: Optional[str], area: Optional[str], detail: bool, tag2name: bool, json: bool) -> None:
        """
        Show routes this node is advertising. Will show all by default
        """
        decision.ReceivedRoutesCmd(self).run(
            prefix, node, area, json, detail, tag2name
        )
