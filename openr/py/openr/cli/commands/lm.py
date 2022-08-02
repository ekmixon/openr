#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.


import sys
from builtins import object
from typing import Any, Dict, List, Sequence, Optional

import click
from openr.cli.utils import utils
from openr.cli.utils.commands import OpenrCtrlCmd
from openr.OpenrCtrl import OpenrCtrl
from openr.Types import ttypes as openr_types
from openr.utils import ipnetwork, printing


class LMCmdBase(OpenrCtrlCmd):
    """
    Base class for LinkMonitor cmds. All of LinkMonitor cmd
    is spawn out of this.
    """

    def toggle_node_overload_bit(
        self, client: OpenrCtrl.Client, overload: bool, yes: bool = False
    ) -> None:
        links = client.getInterfaces()
        host = links.thisNodeName
        print()

        if overload and links.isOverloaded:
            print(f"Node {host} is already overloaded.\n")
            sys.exit(0)

        if not overload and not links.isOverloaded:
            print(f"Node {host} is not overloaded.\n")
            sys.exit(0)

        action = "set overload bit" if overload else "unset overload bit"
        if not utils.yesno(f"Are you sure to {action} for node {host} ?", yes):
            print()
            return

        if overload:
            client.setNodeOverload()
        else:
            client.unsetNodeOverload()

        print(f"Successfully {action}..\n")

    def toggle_link_overload_bit(
        self,
        client: OpenrCtrl.Client,
        overload: bool,
        interface: str,
        yes: bool = False,
    ) -> None:
        links = client.getInterfaces()
        print()

        if interface not in links.interfaceDetails:
            print(f"No such interface: {interface}")
            return

        if overload and links.interfaceDetails[interface].isOverloaded:
            print("Interface is already overloaded.\n")
            sys.exit(0)

        if not overload and not links.interfaceDetails[interface].isOverloaded:
            print("Interface is not overloaded.\n")
            sys.exit(0)

        action = "set overload bit" if overload else "unset overload bit"
        question_str = "Are you sure to {} for interface {} ?"
        if not utils.yesno(question_str.format(action, interface), yes):
            print()
            return

        if overload:
            client.setInterfaceOverload(interface)
        else:
            client.unsetInterfaceOverload(interface)

        print(f"Successfully {action} for the interface.\n")

    def check_link_overriden(
        self, links: openr_types.DumpLinksReply, interface: str, metric: int
    ) -> Optional[bool]:
        """
        This function call will comapre the metricOverride in the following way:
        1) metricOverride NOT set -> return None;
        2) metricOverride set -> return True/False;
        """
        metricOverride = links.interfaceDetails[interface].metricOverride
        return metricOverride == metric if metricOverride else None

    def toggle_link_metric(
        self,
        client: OpenrCtrl.Client,
        override: bool,
        interface: str,
        metric: int,
        yes: bool,
    ) -> None:
        links = client.getInterfaces()
        print()

        if interface not in links.interfaceDetails:
            print(f"No such interface: {interface}")
            return

        status = self.check_link_overriden(links, interface, metric)
        if not override and status is None:
            print("Interface hasn't been assigned metric override.\n")
            sys.exit(0)

        if override and status:
            print(f"Interface: {interface} has already been set with metric: {metric}.\n")
            sys.exit(0)

        action = "set override metric" if override else "unset override metric"
        question_str = "Are you sure to {} for interface {} ?"
        if not utils.yesno(question_str.format(action, interface), yes):
            print()
            return

        if override:
            client.setInterfaceMetric(interface, metric)
        else:
            client.unsetInterfaceMetric(interface)

        print(f"Successfully {action} for the interface.\n")


class SetNodeOverloadCmd(LMCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        yes: bool = False,
        *args,
        **kwargs,
    ) -> None:
        self.toggle_node_overload_bit(client, True, yes)


class UnsetNodeOverloadCmd(LMCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        yes: bool = False,
        *args,
        **kwargs,
    ) -> None:
        self.toggle_node_overload_bit(client, False, yes)


class SetLinkOverloadCmd(LMCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        interface: str,
        yes: bool,
        *args,
        **kwargs,
    ) -> None:
        self.toggle_link_overload_bit(client, True, interface, yes)


class UnsetLinkOverloadCmd(LMCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        interface: str,
        yes: bool,
        *args,
        **kwargs,
    ) -> None:
        self.toggle_link_overload_bit(client, False, interface, yes)


class SetLinkMetricCmd(LMCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        interface: str,
        metric: str,
        yes: bool,
        *args,
        **kwargs,
    ) -> None:
        self.toggle_link_metric(client, True, interface, int(metric), yes)


class UnsetLinkMetricCmd(LMCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        interface: str,
        yes: bool,
        *args,
        **kwargs,
    ) -> None:
        self.toggle_link_metric(client, False, interface, 0, yes)


class SetAdjMetricCmd(LMCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        node: str,
        interface: str,
        metric: str,
        yes: bool,
        *args,
        **kwargs,
    ) -> None:
        client.setAdjacencyMetric(interface, node, int(metric))


class UnsetAdjMetricCmd(LMCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        node: str,
        interface: str,
        yes: bool,
        *args,
        **kwargs,
    ) -> None:
        client.unsetAdjacencyMetric(interface, node)


class LMAdjCmd(LMCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        nodes: set,
        json: bool,
        areas: Sequence[str] = (),
        *args,
        **kwargs,
    ) -> None:
        area_filters = OpenrCtrl.AdjacenciesFilter(selectAreas=set(areas))
        adj_dbs = client.getLinkMonitorAdjacenciesFiltered(area_filters)

        for adj_db in adj_dbs:
            if adj_db and adj_db.area and not json:
                click.secho(f"Area: {adj_db.area}", bold=True)
            # adj_db is built with ONLY one single (node, adjDb). Ignpre bidir option
            adjs_map = utils.adj_dbs_to_dict(
                {adj_db.thisNodeName: adj_db}, nodes, False, self.iter_dbs
            )
            if json:
                utils.print_json(adjs_map)
            else:
                utils.print_adjs_table(adjs_map, None, None)


class LMLinksCmd(LMCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        only_suppressed: bool,
        json: bool,
        *args,
        **kwargs,
    ) -> None:
        links = client.getInterfaces()
        if only_suppressed:
            links.interfaceDetails = {
                k: v for k, v in links.interfaceDetails.items() if v.linkFlapBackOffMs
            }
        if json:
            self.print_links_json(links)
        else:
            if utils.is_color_output_supported():
                overload_color = "red" if links.isOverloaded else "green"
                overload_status = click.style(
                    f'{"YES" if links.isOverloaded else "NO"}', fg=overload_color
                )

                caption = f"Node Overload: {overload_status}"
            else:
                caption = f'Node Overload: {"YES" if links.isOverloaded else "NO"}'

            self.print_links_table(links.interfaceDetails, caption)

    def interface_info_to_dict(self, interface_info):
        def _update(interface_info_dict, interface_info):
            interface_info_dict.update(
                {
                    "networks": [
                        ipnetwork.sprint_prefix(prefix)
                        for prefix in interface_info.networks
                    ]
                }
            )

        return utils.thrift_to_dict(interface_info, _update)

    def interface_details_to_dict(self, interface_details):
        def _update(interface_details_dict, interface_details):
            interface_details_dict.update(
                {"info": self.interface_info_to_dict(interface_details.info)}
            )

        return utils.thrift_to_dict(interface_details, _update)

    def links_to_dict(self, links):
        def _update(links_dict, links):
            links_dict.update(
                {
                    "interfaceDetails": {
                        k: self.interface_details_to_dict(v)
                        for k, v in links.interfaceDetails.items()
                    }
                }
            )
            del links_dict["thisNodeName"]

        return utils.thrift_to_dict(links, _update)

    def print_links_json(self, links):

        links_dict = {links.thisNodeName: self.links_to_dict(links)}
        print(utils.json_dumps(links_dict))

    @classmethod
    def build_table_rows(cls, interfaces: Dict[str, object]) -> List[List[str]]:
        rows = []
        for (k, v) in sorted(interfaces.items()):
            raw_row = cls.build_table_row(k, v)
            addrs = raw_row[3]
            raw_row[3] = ""
            rows.append(raw_row)
            rows.extend(["", "", "", addrStr] for addrStr in addrs)
        return rows

    @staticmethod
    def build_table_row(k: str, v: object) -> List[Any]:
        # pyre-fixme[16]: `object` has no attribute `metricOverride`.
        metric_override = v.metricOverride or ""
        # pyre-fixme[16]: `object` has no attribute `info`.
        if v.info.isUp:
            backoff_sec = int(((v.linkFlapBackOffMs or 0) / 1000))
            if backoff_sec == 0:
                state = "Up"
            elif not utils.is_color_output_supported():
                state = backoff_sec
            else:
                state = click.style(f"Hold ({backoff_sec} s)", fg="yellow")
        else:
            state = (
                click.style("Down", fg="red")
                if utils.is_color_output_supported()
                else "Down"
            )
        # pyre-fixme[16]: `object` has no attribute `isOverloaded`.
        if v.isOverloaded:
            metric_override = (
                click.style("Overloaded", fg="red")
                if utils.is_color_output_supported()
                else "Overloaded"
            )
        addrs = []
        for prefix in v.info.networks:
            addrStr = ipnetwork.sprint_addr(prefix.prefixAddress.addr)
            addrs.append(addrStr)
        return [k, state, metric_override, addrs]

    @classmethod
    def print_links_table(cls, interfaces, caption=None):
        """
        @param interfaces: dict<interface-name, InterfaceDetail>
        @param caption: Caption to show on table name
        """

        columns = ["Interface", "Status", "Metric Override", "Addresses"]
        rows = cls.build_table_rows(interfaces)

        print(printing.render_horizontal_table(rows, columns, caption))
        print()
