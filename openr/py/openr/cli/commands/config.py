#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import json
from typing import Tuple, Optional, Union

import click
import jsondiff
from openr.cli.utils import utils
from openr.cli.utils.commands import OpenrCtrlCmd
from openr.OpenrCtrl import OpenrCtrl
from openr.OpenrCtrl.ttypes import OpenrError
from openr.Types import ttypes as openr_types
from openr.utils import ipnetwork, printing
from openr.utils.consts import Consts
from openr.utils.serializer import deserialize_thrift_object


class ConfigShowCmd(OpenrCtrlCmd):
    def _run(self, client: OpenrCtrl.Client, *args, **kwargs):
        resp = client.getRunningConfig()
        config = json.loads(resp)
        utils.print_json(config)


class ConfigDryRunCmd(OpenrCtrlCmd):
    def _run(self, client: OpenrCtrl.Client, file: str, *args, **kwargs) -> int:
        try:
            file_conf = client.dryrunConfig(file)
        except OpenrError as ex:
            click.echo(click.style(f"FAILED: {ex}", fg="red"))
            return 1

        config = json.loads(file_conf)
        utils.print_json(config)
        return 0


class ConfigCompareCmd(OpenrCtrlCmd):
    def _run(self, client: OpenrCtrl.Client, file: str, *args, **kwargs):
        running_conf = client.getRunningConfig()

        try:
            file_conf = client.dryrunConfig(file)
        except OpenrError as ex:
            click.echo(click.style(f"FAILED: {ex}", fg="red"))
            return

        if res := jsondiff.diff(
            running_conf, file_conf, load=True, syntax="explicit"
        ):
            click.echo(click.style("DIFF FOUND!", fg="red"))
            print(f"== diff(running_conf, {file}) ==")
            print(res)
        else:
            click.echo(click.style("SAME", fg="green"))


class ConfigStoreCmdBase(OpenrCtrlCmd):
    def getConfigWrapper(
        self, client: OpenrCtrl.Client, config_key: str
    ) -> Tuple[Optional[bytes], Optional[str]]:
        blob = None
        exception_str = None
        try:
            blob = client.getConfigKey(config_key)
        except OpenrError as ex:
            exception_str = f"Exception getting key for {config_key}: {ex}"

        return (blob, exception_str)


class ConfigPrefixAllocatorCmd(ConfigStoreCmdBase):
    def _run(self, client: OpenrCtrl.Client, *args, **kwargs):
        (prefix_alloc_blob, exception_str) = self.getConfigWrapper(
            client, Consts.PREFIX_ALLOC_KEY
        )

        if prefix_alloc_blob is None:
            print(exception_str)
            return

        prefix_alloc = deserialize_thrift_object(
            prefix_alloc_blob, openr_types.AllocPrefix
        )
        self.print_config(prefix_alloc)

    def print_config(self, prefix_alloc: openr_types.AllocPrefix) -> None:
        seed_prefix = prefix_alloc.seedPrefix
        seed_prefix_addr = ipnetwork.sprint_addr(seed_prefix.prefixAddress.addr)

        caption = "Prefix Allocator parameters stored"
        rows = [
            [f"Seed prefix: {seed_prefix_addr}/{seed_prefix.prefixLength}"],
            [f"Allocated prefix length: {prefix_alloc.allocPrefixLen}"],
            [f"Allocated prefix index: {prefix_alloc.allocPrefixIndex}"],
        ]

        print(printing.render_vertical_table(rows, caption=caption))


class ConfigLinkMonitorCmd(ConfigStoreCmdBase):
    def _run(self, client: OpenrCtrl.Client, *args, **kwargs) -> None:
        # After link-monitor thread starts, it will hold for
        # "adjHoldUntilTimePoint_" time before populate config information.
        # During this short time-period, Exception can be hit if dump cmd
        # kicks during this time period.
        (lm_config_blob, exception_str) = self.getConfigWrapper(
            client, Consts.LINK_MONITOR_KEY
        )

        if lm_config_blob is None:
            print(exception_str)
            return

        lm_config = deserialize_thrift_object(
            lm_config_blob, openr_types.LinkMonitorState
        )
        self.print_config(lm_config)

    def print_config(self, lm_config: openr_types.LinkMonitorState):
        caption = "Link Monitor parameters stored"
        rows = [
            [f'isOverloaded: {"Yes" if lm_config.isOverloaded else "No"}'],
            [f"nodeLabel: {lm_config.nodeLabel}"],
            [f'overloadedLinks: {", ".join(lm_config.overloadedLinks)}'],
        ]

        print(printing.render_vertical_table(rows, caption=caption))

        print(printing.render_vertical_table([["linkMetricOverrides:"]]))
        column_labels = ["Interface", "Metric Override"]
        rows = [[k, v] for k, v in sorted(lm_config.linkMetricOverrides.items())]
        print(printing.render_horizontal_table(rows, column_labels=column_labels))

        print(printing.render_vertical_table([["adjMetricOverrides:"]]))
        column_labels = ["Adjacency", "Metric Override"]
        rows = []
        for (k, v) in sorted(lm_config.adjMetricOverrides.items()):
            adj_str = f"{k.nodeName} {k.ifName}"
            rows.append([adj_str, v])
        print(printing.render_horizontal_table(rows, column_labels=column_labels))


class ConfigPrefixManagerCmd(ConfigStoreCmdBase):
    def _run(self, client: OpenrCtrl.Client, *args, **kwargs) -> None:
        (prefix_mgr_config_blob, exception_str) = self.getConfigWrapper(
            client, Consts.PREFIX_MGR_KEY
        )

        if prefix_mgr_config_blob is None:
            print(exception_str)
            return

        prefix_mgr_config = deserialize_thrift_object(
            prefix_mgr_config_blob, openr_types.PrefixDatabase
        )
        self.print_config(prefix_mgr_config)

    def print_config(self, prefix_mgr_config: openr_types.PrefixDatabase):
        print()
        print(utils.sprint_prefixes_db_full(prefix_mgr_config))
        print()


class ConfigEraseCmd(ConfigStoreCmdBase):
    def _run(self, client: OpenrCtrl.Client, key: str, *args, **kwargs) -> None:
        client.eraseConfigKey(key)
        print(f"Key:{key} erased")


class ConfigStoreCmd(ConfigStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        key: str,
        value: Union[bytes, str],
        *args,
        **kwargs
    ) -> None:
        if isinstance(value, str):
            value = value.encode()
        client.setConfigKey(key, value)
        print(f"Key:{key}, value:{value} stored")
