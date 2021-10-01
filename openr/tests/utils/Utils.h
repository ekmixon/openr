/*
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#pragma once

#include <openr/common/Constants.h>
#include <openr/common/MplsUtil.h>
#include <openr/common/Types.h>
#include <openr/common/Util.h>
#include <openr/config/Config.h>

#include <openr/if/gen-cpp2/BgpConfig_types.h>
#include <openr/if/gen-cpp2/Types_types.h>

namespace openr {

/*
 * Util function to generate random string of given length
 */
std::string genRandomStr(const int64_t len);

/*
 * Util function to construct thrift::AreaConfig
 */
openr::thrift::AreaConfig createAreaConfig(
    const std::string& areaId,
    const std::vector<std::string>& neighborRegexes,
    const std::vector<std::string>& interfaceRegexes,
    const std::optional<std::string>& policy = std::nullopt,
    const bool enableAdjLabels = false);

/*
 * Util function to genearate basic Open/R config in UT env.
 */
openr::thrift::OpenrConfig getBasicOpenrConfig(
    const std::string& nodeName = "",
    const std::string& domainName = "domain",
    const std::vector<openr::thrift::AreaConfig>& areaCfg = {},
    bool enableV4 = true,
    bool enableSegmentRouting = false,
    bool dryrun = true,
    bool enableV4OverV6Nexthop = false,
    bool enableAdjLabels = false,
    bool enablePrependLabels = false);

} // namespace openr