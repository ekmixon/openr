#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import datetime
import ipaddress
import time
from builtins import object
from typing import List, Optional, Union, Sequence

import prettytable
import pytz
from openr.cli.utils import utils
from openr.cli.utils.commands import OpenrCtrlCmd
from openr.clients.openr_client import get_openr_ctrl_client, get_openr_ctrl_cpp_client
from openr.Network import ttypes as network_types
from openr.OpenrCtrl import OpenrCtrl
from openr.OpenrCtrl.ttypes import StreamSubscriberType
from openr.thrift.Network import types as network_types_py3
from openr.thrift.OpenrCtrlCpp.clients import OpenrCtrlCpp as OpenrCtrlCppClient
from openr.thrift.Types import types as openr_types_py3
from openr.Types import ttypes as openr_types
from openr.utils import ipnetwork, printing
from thrift.py3.client import ClientType


class FibAgentCmd(object):
    def __init__(self, cli_opts):
        """initialize the Fib agent client"""
        self.cli_opts = cli_opts
        try:
            self.client = utils.get_fib_agent_client(
                cli_opts.host,
                cli_opts.fib_agent_port,
                cli_opts.timeout,
                cli_opts.client_id,
            )
        except Exception as e:
            print(f"Failed to get communicate to Fib. {e}")
            print(
                "Note: Specify correct host with -H/--host option and "
                + "make sure that Fib is running on the host or ports "
                + "are open on that box for network communication."
            )
            raise


class FibUnicastRoutesCmd(OpenrCtrlCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        prefix_or_ip: List[str],
        json: bool,
        *args,
        **kwargs,
    ) -> None:
        unicast_route_list = client.getUnicastRoutesFiltered(prefix_or_ip)
        host_name = client.getMyNodeName()

        if json:
            routes = {
                "unicastRoutes": [
                    utils.unicast_route_to_dict(r) for r in unicast_route_list
                ]
            }
            route_dict = {host_name: routes}
            utils.print_routes_json(route_dict)
        else:
            utils.print_unicast_routes(
                f"Unicast Routes for {host_name}", unicast_route_list
            )


class FibMplsRoutesCmd(OpenrCtrlCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        labels: List[int],
        json: bool,
        *args,
        **kwargs,
    ) -> None:
        int_label_filters = [int(label) for label in labels]
        mpls_route_list = client.getMplsRoutesFiltered(int_label_filters)
        host_name = client.getMyNodeName()

        if json:
            routes = {
                "mplsRoutes": [utils.mpls_route_to_dict(r) for r in mpls_route_list]
            }
            route_dict = {host_name: routes}
            utils.print_routes_json(route_dict)
        else:
            utils.print_mpls_routes(f"MPLS Routes for {host_name}", mpls_route_list)


class FibCountersCmd(FibAgentCmd):
    def run(self, json_opt):
        try:
            self.print_counters(self.client.getCounters(), json_opt)
            return 0
        except Exception as e:
            print("Failed to get counter from Fib")
            print(f"Exception: {e}")
            return 1

    def print_counters(self, counters, json_opt):
        """print the Fib counters"""

        with utils.get_openr_ctrl_client(self.cli_opts.host, self.cli_opts) as client:
            host_id = client.getMyNodeName()
        caption = f"{host_id}'s Fib counters"

        if json_opt:
            utils.print_json(counters)
        else:
            rows = [[f"{key} : {counters[key]}"] for key in counters]
            print(
                printing.render_horizontal_table(
                    rows, caption=caption, tablefmt="plain"
                )
            )
            print()


class FibRoutesInstalledCmd(FibAgentCmd):
    def run(
        self,
        prefixes: List[str],
        labels: Optional[List[int]] = None,
        json_opt: bool = False,
        client_id: Optional[int] = None,
    ):
        routes = []
        mpls_routes = []
        client_id = client_id if client_id is not None else self.client.client_id

        try:
            routes = self.client.getRouteTableByClient(client_id)
        except Exception as e:
            print("Failed to get routes from Fib.")
            print(f"Exception: {e}")
            return 1

        try:
            mpls_routes = self.client.getMplsRouteTableByClient(client_id)
        except Exception:
            pass

        if json_opt:
            utils.print_json(
                utils.get_routes_json(
                    "", client_id, routes, prefixes, mpls_routes, labels
                )
            )
        else:
            caption = f"FIB routes by client {client_id}"
            utils.print_unicast_routes(caption, routes, prefixes)
            caption = f"MPLS routes by client {client_id}"
            utils.print_mpls_routes(caption, mpls_routes, labels)

        return 0


class FibAddRoutesCmd(FibAgentCmd):
    def run(self, prefixes, nexthops):
        routes = utils.build_routes(prefixes.split(","), nexthops.split(","))

        try:
            self.client.addUnicastRoutes(self.client.client_id, routes)
        except Exception as e:
            print("Failed to add routes.")
            print(f"Exception: {e}")
            return 1

        print(f"Added {len(routes)} routes.")
        return 0


class FibDelRoutesCmd(FibAgentCmd):
    def run(self, prefixes):
        prefixes = [ipnetwork.ip_str_to_prefix(p) for p in prefixes.split(",")]
        try:
            self.client.deleteUnicastRoutes(self.client.client_id, prefixes)
        except Exception as e:
            print("Failed to delete routes.")
            print(f"Exception: {e}")
            return 1

        print(f"Deleted {len(prefixes)} routes.")
        return 0


class FibSyncRoutesCmd(FibAgentCmd):
    def run(self, prefixes, nexthops):
        routes = utils.build_routes(prefixes.split(","), nexthops.split(","))

        try:
            self.client.syncFib(self.client.client_id, routes)
        except Exception as e:
            print("Failed to sync routes.")
            print(f"Exception: {e}")
            return 1

        print(f"Reprogrammed FIB with {len(routes)} routes.")
        return 0


class FibValidateRoutesCmd(FibAgentCmd):
    def run(self, cli_opts):
        all_success = True

        try:
            decision_route_db = None
            fib_route_db = None
            lm_links = None

            with get_openr_ctrl_client(cli_opts.host, cli_opts) as client:
                # fetch routes from decision module
                decision_route_db = client.getRouteDbComputed("")
                # fetch routes from fib module
                fib_route_db = client.getRouteDb()
                # fetch link_db from link-monitor module
                lm_links = client.getInterfaces().interfaceDetails

            (decision_unicast_routes, decision_mpls_routes) = utils.get_routes(
                decision_route_db
            )
            (fib_unicast_routes, fib_mpls_routes) = utils.get_routes(fib_route_db)
            # fetch route from net_agent module
            agent_unicast_routes = self.client.getRouteTableByClient(
                self.client.client_id
            )

        except Exception as e:
            print("Failed to validate Fib routes.")
            print(f"Exception: {e}")
            raise e
                # return 1

        (ret, _) = utils.compare_route_db(
            decision_unicast_routes,
            fib_unicast_routes,
            "unicast",
            ["Openr-Decision:unicast", "Openr-Fib:unicast"],
        )
        all_success = all_success and ret

        (ret, _) = utils.compare_route_db(
            decision_mpls_routes,
            fib_mpls_routes,
            "mpls",
            ["Openr-Decision:mpls", "Openr-Fib:mpls"],
        )
        all_success = all_success and ret

        (ret, _) = utils.compare_route_db(
            fib_unicast_routes,
            agent_unicast_routes,
            "unicast",
            ["Openr-Fib:unicast", "FibAgent:unicast"],
        )
        all_success = all_success and ret

        # for backward compatibily of Open/R binary
        try:
            agent_mpls_routes = self.client.getMplsRouteTableByClient(
                self.client.client_id
            )
            (ret, _) = utils.compare_route_db(
                fib_mpls_routes,
                agent_mpls_routes,
                "mpls",
                ["Openr-Fib:mpls", "FibAgent:mpls"],
            )
            all_success = all_success and ret
        except Exception:
            pass

        (ret, _) = utils.validate_route_nexthops(
            fib_unicast_routes, lm_links, ["Openr-Fib:unicast", "LinkMonitor"]
        )
        all_success = all_success and ret

        return 0 if all_success else -1


class FibSnoopCmd(OpenrCtrlCmd):
    def print_ip_prefixes_filtered(
        self,
        ip_prefixes: Union[
            Sequence[network_types_py3.IpPrefix], List[network_types.IpPrefix]
        ],
        prefixes_filter: Optional[List[str]] = None,
        element_prefix: str = ">",
        element_suffix: str = "",
    ) -> None:
        """
        Print prefixes. If specified, exact match subset of prefixes_filter
        only will be printed.
        :param unicast_routes: Unicast routes
        :param prefixes_filter: Optional prefixes/filter to print (Exact match).
        :param element_prefix: Starting prefix for each item. (string)
        :param element_suffix: Ending/terminator for each item. (string)
        """

        filter_for_networks = None
        if prefixes_filter:
            filter_for_networks = [ipaddress.ip_network(p) for p in prefixes_filter]

        prefix_strs = [
            [ipnetwork.sprint_prefix(ip_prefix)]
            for ip_prefix in ip_prefixes
            if not filter_for_networks
            or ipaddress.ip_network(ipnetwork.sprint_prefix(ip_prefix))
            in filter_for_networks
        ]

        print(
            printing.render_vertical_table(
                prefix_strs,
                element_prefix=element_prefix,
                element_suffix=element_suffix,
                timestamp=True,
            )
        )

    def print_mpls_labels(
        self,
        labels: Union[List[int], Sequence[int]],
        element_prefix: str = ">",
        element_suffix: str = "",
    ) -> None:
        """
        Print mpls labels. Subset specified by labels_filter only will be printed if specified
        :param labels: mpls labels
        :param element_prefix: Starting prefix for each item. (string)
        :param element_suffix: Ending/terminator for each item. (string)
        """

        label_strs = [[str(label)] for label in labels]

        print(
            printing.render_vertical_table(
                label_strs,
                element_prefix=element_prefix,
                element_suffix=element_suffix,
                timestamp=True,
            )
        )

    def print_route_db_delta(
        self,
        delta_db: Union[
            openr_types.RouteDatabaseDelta,
            openr_types_py3.RouteDatabaseDelta,
        ],
        prefixes: Optional[List[str]] = None,
    ) -> None:
        """print the RouteDatabaseDelta from Fib module"""

        if len(delta_db.unicastRoutesToUpdate) != 0:
            utils.print_unicast_routes(
                caption="",
                unicast_routes=delta_db.unicastRoutesToUpdate,
                prefixes=prefixes,
                element_prefix="+",
                filter_exact_match=True,
                timestamp=True,
            )
        if len(delta_db.unicastRoutesToDelete) != 0:
            self.print_ip_prefixes_filtered(
                ip_prefixes=delta_db.unicastRoutesToDelete,
                prefixes_filter=prefixes,
                element_prefix="-",
            )

        if prefixes:
            return

        if len(delta_db.mplsRoutesToUpdate) != 0:
            utils.print_mpls_routes(
                caption="",
                mpls_routes=delta_db.mplsRoutesToUpdate,
                element_prefix="+",
                element_suffix="(MPLS)",
                timestamp=True,
            )
        if len(delta_db.mplsRoutesToDelete) != 0:
            self.print_mpls_labels(
                labels=delta_db.mplsRoutesToDelete,
                element_prefix="-",
                element_suffix="(MPLS)",
            )

    def print_route_db(
        self,
        route_db: Union[openr_types.RouteDatabase, openr_types_py3.RouteDatabase],
        prefixes: Optional[List[str]] = None,
        labels: Optional[List[int]] = None,
    ) -> None:
        """print the routes from Fib module"""

        if (prefixes or not labels) and len(route_db.unicastRoutes) != 0:
            utils.print_unicast_routes(
                caption="",
                unicast_routes=route_db.unicastRoutes,
                prefixes=prefixes,
                element_prefix="+",
                filter_exact_match=True,
                timestamp=True,
            )
        if (labels or not prefixes) and len(route_db.mplsRoutes) != 0:
            utils.print_mpls_routes(
                caption="",
                mpls_routes=route_db.mplsRoutes,
                labels=labels,
                element_prefix="+",
                element_suffix="(MPLS)",
                timestamp=True,
            )

    # @override
    def run(self, *args, **kwargs) -> int:
        """
        Override run method to create py3 client for streaming.
        """

        async def _wrapper() -> int:
            client_type = ClientType.THRIFT_ROCKET_CLIENT_TYPE
            async with get_openr_ctrl_cpp_client(
                self.host, self.cli_opts, client_type=client_type
            ) as client:
                await self._run(client, *args, **kwargs)
            return 0

        return asyncio.run(_wrapper())

    async def _run(
        self,
        client: OpenrCtrlCppClient,
        duration: int,
        initial_dump: bool,
        prefixes: List[str],
        *args,
        **kwargs,
    ) -> None:

        initialDb, updates = (await client.subscribeAndGetFib()).__iter__()
        # Print summary
        print(f" Routes for {initialDb.thisNodeName}.")
        print(f" {len(initialDb.unicastRoutes)} unicast routes in initial dump.")
        print(f" {len(initialDb.mplsRoutes)} mpls routes in initial dump.\n")
        # Expand initial dump based on input argument
        if initial_dump:
            self.print_route_db(initialDb, prefixes)

        print("RouteDatabaseDelta updates to follow ...\n")

        start_time = time.time()
        awaited_updates = None
        while True:
            # Break if it is time
            if duration > 0 and time.time() - start_time > duration:
                print("Duration expired. Terminating snooping.")
                break

            # Await for an update
            if not awaited_updates:
                awaited_updates = [updates.__anext__()]
            done, awaited_updates = await asyncio.wait(awaited_updates, timeout=1)
            if not done:
                continue
            else:
                msg = await done.pop()

            self.print_route_db_delta(msg, prefixes)


def ip_key(ip):
    net = ipaddress.ip_network(ip)
    return (net.version, net.network_address, net.prefixlen)


def convertTime(intTime):
    formatted_time = datetime.datetime.fromtimestamp(intTime / 1000)
    timezone = pytz.timezone("US/Pacific")
    formatted_time = timezone.localize(formatted_time)
    formatted_time = formatted_time.strftime("%Y-%m-%d %H:%M:%S.%f %Z")
    return formatted_time


class StreamSummaryCmd(OpenrCtrlCmd):
    def get_subscriber_row(self, stream_session_info):
        """
        Takes StreamSubscriberInfo from thrift and returns list[str] (aka row)
        representing the subscriber
        """

        uptime = "unknown"
        last_msg_time = "unknown"
        if (
            stream_session_info.uptime is not None
            and stream_session_info.last_msg_sent_time is not None
        ):
            uptime_str = str(
                datetime.timedelta(milliseconds=stream_session_info.uptime)
            )
            last_msg_time_str = convertTime(stream_session_info.last_msg_sent_time)
            uptime = uptime_str.split(".")[0]
            last_msg_time = last_msg_time_str

        return [
            stream_session_info.subscriber_id,
            uptime,
            stream_session_info.total_streamed_msgs,
            last_msg_time,
        ]

    def run(self, *args, **kwargs) -> int:
        async def _wrapper() -> int:
            client_type = ClientType.THRIFT_ROCKET_CLIENT_TYPE
            async with get_openr_ctrl_cpp_client(
                self.host, self.cli_opts, client_type
            ) as client:
                await self._run(client, *args, **kwargs)
            return 0

        return asyncio.run(_wrapper())

    async def _run(
        self,
        client: OpenrCtrlCppClient,
        *args,
        **kwargs,
    ) -> None:

        subscribers = await client.getSubscriberInfo(StreamSubscriberType.FIB)

        # Prepare the table
        columns = [
            "SubscriberID",
            "Uptime",
            "Total Messages",
            "Time of Last Message",
        ]
        table = ""
        table = prettytable.PrettyTable(columns)
        table.set_style(prettytable.PLAIN_COLUMNS)
        table.align = "l"
        table.left_padding_width = 0
        table.right_padding_width = 2

        for subscriber in sorted(subscribers, key=lambda x: ip_key(x.subscriber_id)):
            table.add_row(self.get_subscriber_row(subscriber))

        # Print header
        print("FIB stream summary information for subscribers\n")

        if not subscribers:
            print("No subscribers available")

        # Print the table body
        print(table)
