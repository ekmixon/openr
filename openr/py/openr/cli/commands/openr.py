#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from openr.cli.utils import utils
from openr.cli.utils.commands import OpenrCtrlCmd
from openr.OpenrCtrl import OpenrCtrl
from openr.utils import printing


class VersionCmd(OpenrCtrlCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        json: bool,
        *args,
        **kwargs,
    ) -> None:
        openr_version = client.getOpenrVersion()
        build_info = client.getBuildInfo()

        if json:
            if build_info.buildPackageName:
                info = utils.thrift_to_dict(build_info)
                print(utils.json_dumps(info))
            version = utils.thrift_to_dict(openr_version)
            print(utils.json_dumps(version))
        else:
            if build_info.buildPackageName:
                print("Build Information")
                print(f"  Built by: {build_info.buildUser}")
                print(f"  Built on: {build_info.buildTime}")
                print(f"  Built at: {build_info.buildHost}")
                print(f"  Build path: {build_info.buildPath}")
                print(f"  Package Name: {build_info.buildPackageName}")
                print(f"  Package Version: {build_info.buildPackageVersion}")
                print(f"  Package Release: {build_info.buildPackageRelease}")
                print(f"  Build Revision: {build_info.buildRevision}")
                print(f"  Build Upstream Revision: {build_info.buildUpstreamRevision}")
                print(f"  Build Platform: {build_info.buildPlatform}")
                print(
                    f"  Build Rule: {build_info.buildRule} ({build_info.buildType}, {build_info.buildTool}, {build_info.buildMode})"
                )

            rows = [
                ["Open Source Version", ":", openr_version.version],
                [
                    "Lowest Supported Open Source Version",
                    ":",
                    openr_version.lowestSupportedVersion,
                ],
            ]

            print(
                printing.render_horizontal_table(
                    rows, column_labels=[], tablefmt="plain"
                )
            )
