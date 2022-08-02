#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.


import json
import time
from typing import Dict, List

import tabulate
from openr.cli.utils import utils
from openr.cli.utils.commands import OpenrCtrlCmd
from openr.OpenrCtrl import OpenrCtrl
from openr.utils import printing


class MonitorCmd(OpenrCtrlCmd):
    def print_log_list_type(self, llist: List) -> str:
        str_txt = "{}".format("".join(llist[0]) + "\n")
        for idx in range(1, len(llist)):
            str_txt += "{:<18} {}".format("", "".join(llist[idx]) + "\n")
        return str_txt

    def print_log_sample(self, log_sample: Dict) -> None:
        columns = ["", ""]
        rows = []
        for _, value0 in log_sample.items():
            for key, value in value0.items():
                if key == "time":
                    value = time.strftime("%H:%M:%S %Y-%m-%d", time.localtime(value))
                if type(value) is list:
                    value = self.print_log_list_type(value)

                rows.append(["{:<17}  {}".format(key, value)])

        print(tabulate.tabulate(rows, headers=columns, tablefmt="plain"))


class CountersCmd(MonitorCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        prefix: str = "",
        json: bool = False,
        *args,
        **kwargs,
    ) -> None:
        resp = client.getCounters()
        self.print_counters(client, resp, prefix, json)

    def print_counters(
        self, client: OpenrCtrl.Client, resp: Dict, prefix: str, json: bool
    ) -> None:
        """print the Kv Store counters"""

        host_id = client.getMyNodeName()
        caption = f"{host_id}'s counters"

        rows = [
            [key, ":", counter]
            for key, counter in sorted(resp.items())
            if key.startswith(prefix)
        ]

        if json:
            json_data = {k: v for k, _, v in rows}
            print(utils.json_dumps(json_data))
        else:
            print(
                printing.render_horizontal_table(
                    rows, caption=caption, tablefmt="plain"
                )
            )
            print()


class LogCmd(MonitorCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        json_opt: bool = False,
        *args,
        **kwargs,
    ) -> None:
        try:
            resp = client.getEventLogs()
            self.print_log_data(resp, json_opt)
        except TypeError:
            host_id = client.getMyNodeName()
            print(f"Incompatible return type. Please upgrade Open/R binary on {host_id}")

    def print_log_data(self, resp, json_opt):
        """print the log data"""

        if json_opt:
            event_logs = [json.loads(event_log) for event_log in resp]
            print(utils.json_dumps(event_logs))

        else:
            for event_log in resp:
                self.print_log_sample(json.loads(event_log))


class StatisticsCmd(MonitorCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        *args,
        **kwargs,
    ) -> None:
        stats_templates = [
            {
                "title": "KvStore Stats",
                "counters": [
                    ("KeyVals", "kvstore.num_keys"),
                    ("Peering Sessions", "kvstore.num_peers"),
                    ("Pending Sync", "kvstore.pending_full_sync"),
                ],
                "stats": [
                    ("Rcvd Publications", "kvstore.received_publications.count"),
                    ("Rcvd KeyVals", "kvstore.received_key_vals.sum"),
                    ("Updates KeyVals", "kvstore.updated_key_vals.sum"),
                ],
            },
            {
                "title": "LinkMonitor/Spark Stats",
                "counters": [
                    ("Adjacent Neighbors", "spark.num_adjacent_neighbors"),
                    ("Tracked Neighbors", "spark.num_tracked_neighbors"),
                ],
                "stats": [
                    ("Updates AdjDb", "link_monitor.advertise_adjacencies.sum"),
                    ("Rcvd Hello Pkts", "spark.hello.packet_recv.sum"),
                    ("Sent Hello Pkts", "spark.hello.packet_sent.sum"),
                ],
            },
            {
                "title": "Decision/Fib Stats",
                "counters": [],
                "stats": [
                    ("Updates AdjDbs", "decision.adj_db_update.count"),
                    ("Updates PrefixDbs", "decision.prefix_db_update.count"),
                    ("SPF Runs", "decision.spf_runs.count"),
                    ("SPF Avg Duration (ms)", "decision.spf_ms.avg"),
                    ("Convergence Duration (ms)", "fib.convergence_time_ms.avg"),
                    ("Updates RouteDb", "fib.process_route_db.count"),
                    ("Full Route Sync", "fib.sync_fib_calls.count"),
                ],
            },
        ]

        counters = client.getCounters()
        self.print_stats(stats_templates, counters)
