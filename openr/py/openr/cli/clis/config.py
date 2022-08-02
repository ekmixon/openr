#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.


import click
from bunch import Bunch
from openr.cli.commands import config


class ConfigCli:
    def __init__(self):
        self.config.add_command(ConfigShowCli().show, name="show")
        self.config.add_command(ConfigDryRunCli().dryrun, name="dryrun")
        self.config.add_command(ConfigCompareCli().compare, name="compare")
        self.config.add_command(
            ConfigPrefixAllocatorCli().config_prefix_allocator,
            name="prefix-allocator-config",
        )
        self.config.add_command(
            ConfigLinkMonitorCli().config_link_monitor, name="link-monitor-config"
        )
        self.config.add_command(
            ConfigPrefixManagerCli().config_prefix_manager, name="prefix-manager-config"
        )
        self.config.add_command(ConfigEraseCli().config_erase, name="erase")
        self.config.add_command(ConfigStoreCli().config_store, name="store")

    @click.group()
    @click.pass_context
    def config(self) -> None:    # noqa: B902
        """CLI tool to peek into Config Store module."""
        pass


class ConfigShowCli:
    @click.command()
    @click.pass_obj
    def show(self) -> None:    # noqa: B902
        """Show openr running config"""

        config.ConfigShowCmd(self).run()


class ConfigDryRunCli:
    @click.command()
    @click.argument("file")
    @click.pass_obj
    @click.pass_context
    def dryrun(self, cli_opts: Bunch, file: str) -> None:    # noqa: B902
        """Dryrun/validate openr config, output JSON parsed config upon success"""

        config.ConfigDryRunCmd(cli_opts).run(file)
        # TODO(@cooper): Fix emulation to handle UNIX return codes
        # neteng/emulation/emulator/testing/openr/test_breeze.py expects all to return 0
        # This is incorrect and needs to be fixed
        # ret_val = config.ConfigDryRunCmd(cli_opts).run(file)
        # ctx.exit(ret_val if ret_val else 0)


class ConfigCompareCli:
    @click.command()
    @click.argument("file")
    @click.pass_obj
    def compare(self, file: str) -> None:    # noqa: B902
        """Migration cli: Compare config with current running config"""

        config.ConfigCompareCmd(self).run(file)


class ConfigPrefixAllocatorCli:
    @click.command()
    @click.pass_obj
    def config_prefix_allocator(self):    # noqa: B902
        """Dump prefix allocation config"""

        config.ConfigPrefixAllocatorCmd(self).run()


class ConfigLinkMonitorCli:
    @click.command()
    @click.pass_obj
    def config_link_monitor(self):    # noqa: B902
        """Dump link monitor config"""

        config.ConfigLinkMonitorCmd(self).run()


class ConfigPrefixManagerCli:
    @click.command()
    @click.pass_obj
    def config_prefix_manager(self):    # noqa: B902
        """Dump prefix manager config"""

        config.ConfigPrefixManagerCmd(self).run()


class ConfigEraseCli:
    @click.command()
    @click.argument("key")
    @click.pass_obj
    def config_erase(self, key):    # noqa: B902
        """Erase a config key"""

        config.ConfigEraseCmd(self).run(key)


class ConfigStoreCli:
    @click.command()
    @click.argument("key")
    @click.argument("value")
    @click.pass_obj
    def config_store(self, key, value):    # noqa: B902
        """Store a config key"""

        config.ConfigStoreCmd(self).run(key, value)
