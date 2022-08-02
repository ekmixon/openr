#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.


import asyncio
import datetime
import hashlib
import ipaddress
import json
import re
import string
import sys
import time
from builtins import str
from collections.abc import Iterable
from itertools import combinations
from typing import Any, Callable, Dict, List, Optional, Set, AbstractSet

import bunch
import hexdump
import prettytable
import pytz
from openr.cli.utils import utils
from openr.cli.utils.commands import OpenrCtrlCmd
from openr.clients.openr_client import get_openr_ctrl_client, get_openr_ctrl_cpp_client
from openr.KvStore import ttypes as kvstore_types
from openr.Network import ttypes as network_types
from openr.OpenrCtrl import OpenrCtrl
from openr.OpenrCtrl.ttypes import StreamSubscriberType
from openr.thrift.KvStore import types as kvstore_types_py3
from openr.thrift.OpenrCtrlCpp.clients import OpenrCtrlCpp as OpenrCtrlCppClient
from openr.Types import ttypes as openr_types
from openr.utils import ipnetwork, printing, serializer
from openr.utils.consts import Consts
from thrift.py3.client import ClientType


class KvStoreCmdBase(OpenrCtrlCmd):
    def __init__(self, cli_opts: bunch.Bunch):
        super().__init__(cli_opts)
        self.area_feature: bool = False
        self.areas: Set = set()

    def _init_area(self, client: OpenrCtrl.Client) -> None:
        # find out if area feature is supported
        # TODO: remove self.area_feature as it will be supported by default
        self.area_feature = True

        # get list of areas if area feature is supported.
        self.areas = set()
        if self.area_feature:
            self.areas = utils.get_areas_list(client)
            if self.cli_opts.area != "":
                if self.cli_opts.area in self.areas:
                    self.areas = {self.cli_opts.area}
                else:
                    print(f"Invalid area specified: {self.cli_opts.area}")
                    print(f"Valid areas: {self.areas}")
                    sys.exit(1)

    # @override
    def run(self, *args, **kwargs) -> int:
        """
        run method that invokes _run with client and arguments
        """

        with get_openr_ctrl_client(self.host, self.cli_opts) as client:
            self._init_area(client)
            self._run(client, *args, **kwargs)
        return 0

    def print_publication_delta(
        self,
        title: str,
        pub_update: List[str],
        sprint_db: str = "",
        timestamp=False,
    ) -> None:
        print(
            printing.render_vertical_table(
                [
                    [
                        "{}\n{}{}".format(
                            title,
                            pub_update,
                            f"\n\n{sprint_db}" if sprint_db else "",
                        )
                    ]
                ],
                timestamp=timestamp,
            )
        )

    def iter_publication(
        self,
        container: Any,
        publication: Any,
        nodes: set,
        parse_func: Callable[[Any, str], None],
    ) -> None:
        """
        parse dumped publication

        @param: container - Any: container to store the generated data
        @param: publication - kvstore_types.Publication: the publication for parsing
        @param: nodes - set: the set of nodes for parsing
        @param: parse_func - function: the parsing function
        """

        for (key, value) in sorted(publication.keyVals.items(), key=lambda x: x[0]):
            reported_node_name = key.split(":")[1]
            if "all" not in nodes and reported_node_name not in nodes:
                continue

            parse_func(container, value)

    def get_node_to_ips(
        self, client: OpenrCtrl.Client, area: Optional[str] = None
    ) -> Dict:
        """get the dict of all nodes to their IP in the network"""

        keyDumpParams = self.buildKvStoreKeyDumpParams(Consts.PREFIX_DB_MARKER)
        resp = kvstore_types.Publication()
        if not self.area_feature:
            resp = client.getKvStoreKeyValsFiltered(keyDumpParams)
        else:
            if area is None:
                print(f"Error: Must specify one of the areas: {self.areas}")
                sys.exit(1)
            resp = client.getKvStoreKeyValsFilteredArea(keyDumpParams, area)

        prefix_maps = utils.collate_prefix_keys(resp.keyVals)
        return {
            node: self.get_node_ip(prefix_db)
            for node, prefix_db in prefix_maps.items()
        }

    def get_node_ip(self, prefix_db: openr_types.PrefixDatabase) -> Any:
        """get routable IP address of node from it's prefix database"""

        # First look for LOOPBACK prefix
        for prefix_entry in prefix_db.prefixEntries:
            if prefix_entry.type == network_types.PrefixType.LOOPBACK:
                return ipnetwork.sprint_addr(prefix_entry.prefix.prefixAddress.addr)

        return next(
            (
                utils.alloc_prefix_to_loopback_ip_str(prefix_entry.prefix)
                for prefix_entry in prefix_db.prefixEntries
                if prefix_entry.type == network_types.PrefixType.PREFIX_ALLOCATOR
            ),
            None,
        )

    def get_area_id(self) -> str:
        if not self.area_feature:
            print("Try to call get_area_id() without enabling area feature.")
            sys.exit(1)
        if len(self.areas) != 1:
            print(f"Error: Must specify one of the areas: {self.areas}")
            sys.exit(1)
        (area,) = self.areas
        return area


class KvPrefixesCmd(KvStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        nodes: set,
        json: bool,
        prefix: str,
        client_type: str,
        *args,
        **kwargs,
    ) -> None:
        keyDumpParams = self.buildKvStoreKeyDumpParams(Consts.PREFIX_DB_MARKER)
        resp = client.getKvStoreKeyValsFiltered(keyDumpParams)
        self.print_prefix({"": resp}, nodes, json, prefix, client_type)

    def print_prefix(
        self,
        resp: Dict[str, kvstore_types.Publication],
        nodes: set,
        json: bool,
        prefix: str,
        client_type: str,
    ):
        all_kv = kvstore_types.Publication()
        all_kv.keyVals = {}
        for val in resp.values():
            all_kv.keyVals |= val.keyVals
        if json:
            utils.print_prefixes_json(
                all_kv, nodes, prefix, client_type, self.iter_publication
            )
        else:
            utils.print_prefixes_table(
                all_kv, nodes, prefix, client_type, self.iter_publication
            )


class PrefixesCmd(KvPrefixesCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        nodes: set,
        json: bool,
        prefix: str = "",
        client_type: str = "",
        *args,
        **kwargs,
    ) -> None:
        if not self.area_feature:
            super()._run(client, nodes, json, prefix, client_type)
            return
        keyDumpParams = self.buildKvStoreKeyDumpParams(Consts.PREFIX_DB_MARKER)
        area_kv = {}
        for area in self.areas:
            resp = client.getKvStoreKeyValsFilteredArea(keyDumpParams, area)
            area_kv[area] = resp
        self.print_prefix(area_kv, nodes, json, prefix, client_type)


class KvKeysCmd(KvStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        json: bool,
        prefix: Any,
        originator: Any = None,
        ttl: bool = False,
        *args,
        **kwargs,
    ) -> None:
        keyDumpParams = self.buildKvStoreKeyDumpParams(
            prefix, {originator} if originator else None
        )
        resp = client.getKvStoreKeyValsFiltered(keyDumpParams)
        self.print_kvstore_keys({"": resp}, ttl, json)

    def print_kvstore_keys(
        self, resp: Dict[str, kvstore_types.Publication], ttl: bool, json: bool
    ) -> None:
        """print keys from raw publication from KvStore"""

        # Export in json format if enabled
        if json:
            all_kv = {}
            for kv in resp.values():
                all_kv |= kv.keyVals

            # Force set value to None
            for value in all_kv.values():
                value.value = None

            data = {k: utils.thrift_to_dict(v) for k, v in all_kv.items()}
            print(utils.json_dumps(data))
            return

        rows = []
        db_bytes = 0
        num_keys = 0
        for area in resp:
            keyVals = resp[area].keyVals
            num_keys += len(keyVals)
            area_str = "N/A" if area is None else area
            for key, value in sorted(keyVals.items(), key=lambda x: x[0]):
                # 32 bytes comes from version, ttlVersion, ttl and hash which are i64
                bytes_value = value.value
                bytes_len = len(bytes_value if bytes_value is not None else b"")
                kv_size = 32 + len(key) + len(value.originatorId) + bytes_len
                db_bytes += kv_size

                hash_num = value.hash
                hash_offset = "+" if hash_num is not None and hash_num > 0 else ""

                row = [
                    key,
                    value.originatorId,
                    value.version,
                    f"{hash_offset}{value.hash:x}",
                    printing.sprint_bytes(kv_size),
                    area_str,
                ]
                if ttl:
                    ttlStr = (
                        "Inf"
                        if value.ttl == Consts.CONST_TTL_INF
                        else str(datetime.timedelta(milliseconds=value.ttl))
                    )
                    row.append(f"{ttlStr} - {value.ttlVersion}")
                rows.append(row)

        db_bytes_str = printing.sprint_bytes(db_bytes)
        caption = f"KvStore Data - {num_keys} keys, {db_bytes_str}"
        column_labels = ["Key", "Originator", "Ver", "Hash", "Size", "Area"]
        if ttl:
            column_labels += ["TTL - Ver"]

        print(printing.render_horizontal_table(rows, column_labels, caption))


class KeysCmd(KvKeysCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        json: bool,
        prefix: Any,
        originator: Any = None,
        ttl: bool = False,
        *args,
        **kwargs,
    ) -> None:
        if not self.area_feature:
            super()._run(client, json, prefix, originator, ttl)
            return

        keyDumpParams = self.buildKvStoreKeyDumpParams(
            prefix, {originator} if originator else None
        )

        area_kv = {}
        for area in self.areas:
            resp = client.getKvStoreKeyValsFilteredArea(keyDumpParams, area)
            area_kv[area] = resp

        self.print_kvstore_keys(area_kv, ttl, json)


class KvKeyValsCmd(KvStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        keys: List[str],
        *args,
        **kwargs,
    ) -> None:
        resp = client.getKvStoreKeyVals(keys)
        self.print_kvstore_values(resp)

    def deserialize_kvstore_publication(self, key, value):
        """classify kvstore prefix and return the corresponding deserialized obj"""

        options = {
            Consts.PREFIX_DB_MARKER: openr_types.PrefixDatabase,
            Consts.ADJ_DB_MARKER: openr_types.AdjacencyDatabase,
        }

        prefix_type = key.split(":")[0] + ":"
        if prefix_type in options:
            return serializer.deserialize_thrift_object(
                value.value, options[prefix_type]
            )
        else:
            return None

    def print_kvstore_values(
        self,
        resp: kvstore_types.Publication,
        area: Optional[str] = None,
    ) -> None:
        """print values from raw publication from KvStore"""

        rows = []
        for key, value in sorted(resp.keyVals.items(), key=lambda x: x[0]):
            val = self.deserialize_kvstore_publication(key, value)
            if not val:
                if isinstance(value.value, Iterable) and all(
                    isinstance(c, str) and c in string.printable for c in value.value
                ):
                    val = value.value
                else:
                    val = hexdump.hexdump(value.value, "return")

            ttl = "INF" if value.ttl == Consts.CONST_TTL_INF else value.ttl
            rows.append(
                [
                    f"key: {key}\n  version: {value.version}\n  originatorId: {value.originatorId}\n  ttl: {ttl}\n  ttlVersion: {value.ttlVersion}\n  value:\n    {val}"
                ]
            )


        area = f"in area {area}" if area is not None else ""
        caption = f"Dump key-value pairs in KvStore {area}"
        print(printing.render_vertical_table(rows, caption=caption))


class KeyValsCmd(KvKeyValsCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        keys: List[str],
        *args,
        **kwargs,
    ) -> None:
        if not self.area_feature:
            super()._run(client, keys)
            return

        for area in self.areas:
            resp = client.getKvStoreKeyValsArea(keys, area)
            if len(resp.keyVals):
                self.print_kvstore_values(resp, area)


class KvNodesCmd(KvStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        *args,
        **kwargs,
    ) -> None:
        prefix_keys = client.getKvStoreKeyValsFiltered(
            self.buildKvStoreKeyDumpParams(Consts.PREFIX_DB_MARKER)
        )
        adj_keys = client.getKvStoreKeyValsFiltered(
            self.buildKvStoreKeyDumpParams(Consts.ADJ_DB_MARKER)
        )
        host_id = client.getMyNodeName()
        self.print_kvstore_nodes(
            self.get_connected_nodes(adj_keys, host_id), prefix_keys, host_id
        )

    def get_connected_nodes(
        self, adj_keys: kvstore_types.Publication, node_id: str
    ) -> Set[str]:
        """
        Build graph of adjacencies and return list of connected node from
        current node-id
        """
        import networkx as nx

        edges = set()
        graph = nx.Graph()
        for adj_value in adj_keys.keyVals.values():
            adj_db = serializer.deserialize_thrift_object(
                adj_value.value, openr_types.AdjacencyDatabase
            )
            graph.add_node(adj_db.thisNodeName)
            for adj in adj_db.adjacencies:
                # Add edge only when we see the reverse side of it.
                if (adj.otherNodeName, adj_db.thisNodeName, adj.otherIfName) in edges:
                    graph.add_edge(adj.otherNodeName, adj_db.thisNodeName)
                    continue
                edges.add((adj_db.thisNodeName, adj.otherNodeName, adj.ifName))
        # pyre-ignore[16]
        return nx.node_connected_component(graph, node_id)

    def print_kvstore_nodes(
        self,
        connected_nodes: Set[str],
        prefix_keys: kvstore_types.Publication,
        host_id: str,
        node_area: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Print kvstore nodes information. Their loopback and reachability
        information.
        """

        def _parse_loopback_addrs(addrs, value):
            v4_addrs = addrs["v4"]
            v6_addrs = addrs["v6"]
            prefix_db = serializer.deserialize_thrift_object(
                value.value, openr_types.PrefixDatabase
            )

            for prefixEntry in prefix_db.prefixEntries:
                p = prefixEntry.prefix
                if prefixEntry.type != network_types.PrefixType.LOOPBACK:
                    continue

                if len(p.prefixAddress.addr) == 16 and p.prefixLength == 128:
                    v6_addrs[prefix_db.thisNodeName] = ipnetwork.sprint_prefix(p)

                if len(p.prefixAddress.addr) == 4 and p.prefixLength == 32:
                    v4_addrs[prefix_db.thisNodeName] = ipnetwork.sprint_prefix(p)

        # Extract loopback addresses
        addrs = {"v4": {}, "v6": {}}
        self.iter_publication(addrs, prefix_keys, {"all"}, _parse_loopback_addrs)

        # Create rows to print
        rows = []
        for node in set(list(addrs["v4"].keys()) + list(addrs["v6"].keys())):
            marker = "* " if node == host_id else "> "
            loopback_v4 = addrs["v4"].get(node, "N/A")
            loopback_v6 = addrs["v6"].get(node, "N/A")
            area_str = node_area.get(node, "N/A") if node_area is not None else "N/A"
            rows.append(
                [
                    f"{marker}{node}",
                    loopback_v6,
                    loopback_v4,
                    "Reachable" if node in connected_nodes else "Unreachable",
                    area_str,
                ]
            )

        label = ["Node", "V6-Loopback", "V4-Loopback", "Status", "Area"]

        print(printing.render_horizontal_table(rows, label))


class NodesCmd(KvNodesCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        *args,
        **kwargs,
    ) -> None:
        if not self.area_feature:
            super()._run(client)
            return

        all_kv = kvstore_types.Publication()
        all_kv.keyVals = {}
        node_area = {}
        nodes = set()
        for area in self.areas:
            prefix_keys = client.getKvStoreKeyValsFilteredArea(
                self.buildKvStoreKeyDumpParams(Consts.PREFIX_DB_MARKER), area
            )
            all_kv.keyVals.update(prefix_keys.keyVals)
            adj_keys = client.getKvStoreKeyValsFilteredArea(
                self.buildKvStoreKeyDumpParams(Consts.ADJ_DB_MARKER), area
            )
            host_id = client.getMyNodeName()
            node_set = self.get_connected_nodes(adj_keys, host_id)
            # save area associated with each node
            for node in node_set:
                node_area[node] = area
            nodes.update(node_set)

        # pyre-fixme[61]: `host_id` may not be initialized here.
        self.print_kvstore_nodes(nodes, all_kv, host_id, node_area)


class Areas(KvStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        in_json: bool,
        *args,
        **kwargs,
    ) -> None:
        if not self.area_feature:
            return

        if in_json:
            print(json.dumps(list(self.areas)))
        else:
            print(f"Areas configured: {self.areas}")


class FloodCmd(KvStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        roots: List[str],
        *args,
        **kwargs,
    ) -> None:
        for area in self.areas:
            spt_infos = client.getSpanningTreeInfos(area)
            utils.print_spt_infos(spt_infos, roots, area)


class KvShowAdjNodeCmd(KvStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        nodes: set,
        node: Any,
        interface: Any,
        *args,
        **kwargs,
    ) -> None:
        keyDumpParams = self.buildKvStoreKeyDumpParams(Consts.ADJ_DB_MARKER)
        publication = client.getKvStoreKeyValsFiltered(keyDumpParams)
        self.printAdjNode(publication, nodes, node, interface)

    def printAdjNode(self, publication, nodes, node, interface):
        adjs_map = utils.adj_dbs_to_dict(
            publication, nodes, True, self.iter_publication
        )
        utils.print_adjs_table(adjs_map, node, interface)


class ShowAdjNodeCmd(KvShowAdjNodeCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        nodes: set,
        node: Any,
        interface: Any,
        *args,
        **kwargs,
    ) -> None:
        if not self.area_feature:
            super()._run(client, nodes, node, interface, args, kwargs)
            return

        keyDumpParams = self.buildKvStoreKeyDumpParams(Consts.ADJ_DB_MARKER)
        resp = kvstore_types.Publication()
        resp.keyVals = {}
        for area in self.areas:
            publication = client.getKvStoreKeyValsFilteredArea(keyDumpParams, area)
            resp.keyVals.update(publication.keyVals)
        self.printAdjNode(resp, nodes, node, interface)


class KvCompareCmd(KvStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        nodes_in: str,
        *args,
        **kwargs,
    ) -> None:
        area = self.get_area_id()

        all_nodes_to_ips = self.get_node_to_ips(client, area)
        if nodes_in:
            nodes = set(nodes_in.strip().split(","))
            if "all" in nodes:
                nodes = set(all_nodes_to_ips.keys())
            host_id = client.getMyNodeName()
            if host_id in nodes:
                nodes.remove(host_id)

            keyDumpParams = self.buildKvStoreKeyDumpParams(Consts.ALL_DB_MARKER)
            pub = None
            pub = (
                client.getKvStoreKeyValsFilteredArea(keyDumpParams, area)
                if self.area_feature
                else client.getKvStoreKeyValsFiltered(keyDumpParams)
            )

            kv_dict = self.dump_nodes_kvs(nodes, all_nodes_to_ips, area)
            for node in kv_dict:
                self.compare(pub.keyVals, kv_dict[node], host_id, node)
        else:
            nodes = set(all_nodes_to_ips.keys())
            kv_dict = self.dump_nodes_kvs(nodes, all_nodes_to_ips, area)
            for our_node, other_node in combinations(kv_dict.keys(), 2):
                self.compare(
                    kv_dict[our_node], kv_dict[other_node], our_node, other_node
                )

    def compare(self, our_kvs, other_kvs, our_node, other_node):
        """print kv delta"""

        print(printing.caption_fmt(f"kv-compare between {our_node} and {other_node}"))

        # for comparing version and id info
        our_kv_pub_db = {
            key: (value.version, value.originatorId)
            for key, value in our_kvs.items()
        }

        for key, value in sorted(our_kvs.items()):
            other_val = other_kvs.get(key, None)
            if other_val is None:
                self.print_key_delta(key, our_node)

            elif (
                key.startswith(Consts.PREFIX_DB_MARKER)
                or key.startswith(Consts.ADJ_DB_MARKER)
                or other_val.value != value.value
            ):
                self.print_db_delta(key, our_kv_pub_db, value, other_val)

        for key, _ in sorted(other_kvs.items()):
            ourVal = our_kvs.get(key, None)
            if ourVal is None:
                self.print_key_delta(key, other_node)

    def print_db_delta(self, key, our_kv_pub_db, value, other_val):
        """print db delta"""

        if key.startswith(Consts.PREFIX_DB_MARKER):
            prefix_db = serializer.deserialize_thrift_object(
                value.value, openr_types.PrefixDatabase
            )
            other_prefix_db = serializer.deserialize_thrift_object(
                other_val.value, openr_types.PrefixDatabase
            )
            other_prefix_set = {}
            utils.update_global_prefix_db(other_prefix_set, other_prefix_db)
            lines = utils.sprint_prefixes_db_delta(other_prefix_set, prefix_db)

        elif key.startswith(Consts.ADJ_DB_MARKER):
            adj_db = serializer.deserialize_thrift_object(
                value.value, openr_types.AdjacencyDatabase
            )
            other_adj_db = serializer.deserialize_thrift_object(
                value.value, openr_types.AdjacencyDatabase
            )
            lines = utils.sprint_adj_db_delta(adj_db, other_adj_db)

        else:
            lines = None

        if lines != []:
            self.print_publication_delta(
                f"Key: {key} difference",
                utils.sprint_pub_update(our_kv_pub_db, key, other_val),
                "\n".join(lines) if lines else "",
            )

    def print_key_delta(self, key, node):
        """print key delta"""

        print(
            printing.render_vertical_table(
                [[f"key: {key} only in {node} kv store"]]
            )
        )

    def dump_nodes_kvs(
        self, nodes: set, all_nodes_to_ips: Dict, area: Optional[str] = None
    ):
        """get the kvs of a set of nodes"""

        kv_dict = {}
        for node in nodes:
            node_ip = all_nodes_to_ips.get(node, node)
            kv = utils.dump_node_kvs(self.cli_opts, node_ip, area)
            if kv is not None:
                kv_dict[node] = kv.keyVals
                print(f"dumped kv from {node}")
        return kv_dict


class KvPeersCmd(KvStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        *args,
        **kwargs,
    ) -> None:
        peers = client.getKvStorePeers()
        self.print_peers(client, {"": peers})

    def print_peers(self, client: OpenrCtrl.Client, peers_list: Dict[str, Any]) -> None:
        """print the Kv Store peers"""

        host_id = client.getMyNodeName()
        caption = f"{host_id}'s peers"

        rows = []
        for area, peers in peers_list.items():
            area = area if area is not None else "N/A"
            for (key, value) in sorted(peers.items(), key=lambda x: x[0]):
                row = [f"{key}, area:{area}", f"cmd via {value.cmdUrl}"]
                rows.append(row)

        print(printing.render_vertical_table(rows, caption=caption))


class PeersCmd(KvPeersCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        *args,
        **kwargs,
    ) -> None:
        if not self.area_feature:
            super()._run(client)
            return
        peers_list = {area: client.getKvStorePeersArea(area) for area in self.areas}
        self.print_peers(client, peers_list)


class EraseKeyCmd(KvStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        key: str,
        *args,
        **kwargs,
    ) -> None:
        area = self.get_area_id()
        publication = client.getKvStoreKeyValsArea([key], area)
        keyVals = publication.keyVals

        if key not in keyVals:
            print(f"Error: Key {key} not found in KvStore.")
            sys.exit(1)

        # Get and modify the key
        val = keyVals.get(key)

        newVal = kvstore_types.Value()
        newVal.version = getattr(val, "version", 0)
        newVal.originatorId = getattr(val, "originatorId", "")
        newVal.hash = getattr(val, "hash", 0)
        newVal.value = None
        newVal.ttl = 256  # set new ttl to 256ms (its decremented 1ms on every hop)
        newVal.ttlVersion = getattr(val, "ttlVersion", 0) + 1  # bump up ttl version

        print(keyVals)
        keyVals[key] = newVal

        client.setKvStoreKeyVals(kvstore_types.KeySetParams(keyVals), area)

        print(f"Success: key {key} will be erased soon from all KvStores.")


class SetKeyCmd(KvStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        key: str,
        value: Any,
        originator: str,
        version: Any,
        ttl: int,
        *args,
        **kwargs,
    ) -> None:
        area = self.get_area_id()
        val = kvstore_types.Value()

        if version is None:
            # Retrieve existing Value from KvStore
            publication = None
            if area is None:
                publication = client.getKvStoreKeyVals([key])
            else:
                publication = client.getKvStoreKeyValsArea([key], area)
            if key in publication.keyVals:
                existing_val = publication.keyVals.get(key)
                curr_version = getattr(existing_val, "version", 0)
                print(
                    f"Key {key} found in KvStore w/ version {curr_version}. Overwriting with higher version ..."
                )

                version = curr_version + 1
            else:
                version = 1
        val.version = version

        val.originatorId = originator
        val.value = value
        val.ttl = ttl
        val.ttlVersion = 1

        # Advertise publication back to KvStore
        keyVals = {key: val}
        client.setKvStoreKeyVals(kvstore_types.KeySetParams(keyVals), area)
        print(
            f'Success: Set key {key} with version {val.version} and ttl {val.ttl if val.ttl != Consts.CONST_TTL_INF else "infinity"} successfully in KvStore. This does not guarantee that value is updated in KvStore as old value can be persisted back'
        )


class KvSignatureCmd(KvStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        prefix: str,
        *args,
        **kwargs,
    ) -> None:
        area = self.get_area_id()
        keyDumpParams = self.buildKvStoreKeyDumpParams(prefix)
        resp = None
        if area is None:
            resp = client.getKvStoreHashFiltered(keyDumpParams)
        else:
            resp = client.getKvStoreHashFilteredArea(keyDumpParams, area)

        signature = hashlib.sha256()
        for _, value in sorted(resp.keyVals.items(), key=lambda x: x[0]):
            signature.update(str(value.hash).encode("utf-8"))

        print(f"sha256: {signature.hexdigest()}")


class SnoopCmd(KvStoreCmdBase):

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
        delta: bool,
        ttl: bool,
        regexes: Optional[List[str]],
        duration: int,
        originator_ids: Optional[AbstractSet[str]],
        match_all: bool,
        select_areas: Set[str],
        print_initial: bool,
        *args,
        **kwargs,
    ) -> None:
        kvDumpParams = kvstore_types_py3.KeyDumpParams(
            ignoreTtl=not ttl,
            keys=regexes,
            originatorIds=originator_ids,
            oper=kvstore_types_py3.FilterOperator.AND
            if match_all
            else kvstore_types_py3.FilterOperator.OR,
        )

        print("Retrieving and subcribing KvStore ... ")
        # pyre-fixme[23]: Unable to unpack
        # ResponseAndClientBufferedStream__List__Types_Publication_Types_Publication
        (snapshot, updates) = await client.subscribeAndGetAreaKvStores(
            kvDumpParams,
            select_areas,
        )
        global_dbs = self.process_snapshot(snapshot)
        if print_initial:
            for pub in snapshot:
                self.print_delta(pub, ttl, delta, global_dbs[pub.area])
        print(
            f"\nSnooping on areas {','.join(global_dbs.keys())}. Magic begins here ... \n"
        )

        start_time = time.time()
        awaited_updates = None
        while not (duration > 0 and time.time() - start_time > duration):
            # Await for an update
            if not awaited_updates:
                awaited_updates = [updates.__anext__()]
            done, awaited_updates = await asyncio.wait(awaited_updates, timeout=1)
            if not done:
                continue
            else:
                msg = await done.pop()

            if msg.area in global_dbs:
                self.print_expired_keys(msg, global_dbs[msg.area])
                self.print_delta(msg, ttl, delta, global_dbs[msg.area])
            else:
                print(f"ERROR: got publication for unexpected area: {msg.area}")

    def print_expired_keys(self, msg: kvstore_types.Publication, global_dbs: Dict):
        rows = []
        if len(msg.expiredKeys):
            print(f"Traversal List: {msg.nodeIds}")

        for key in msg.expiredKeys:
            rows.append([f"Key: {key} got expired"])

            # Delete key from global DBs
            global_dbs["publications"].pop(key, None)
            if key.startswith(Consts.ADJ_DB_MARKER):
                global_dbs["adjs"].pop(key.split(":")[1], None)

            if key.startswith(Consts.PREFIX_DB_MARKER):
                if prefix_match := re.match(Consts.PER_PREFIX_KEY_REGEX, key):
                    addr_str = prefix_match["ipaddr"]
                    prefix_len = prefix_match["plen"]
                    prefix_set = {f"{addr_str}/{prefix_len}"}
                    node_prefix_set = global_dbs["prefixes"][prefix_match["node"]]
                    node_prefix_set = node_prefix_set - prefix_set
                else:
                    global_dbs["prefixes"].pop(key.split(":")[1], None)
        if rows:
            print(printing.render_vertical_table(rows, timestamp=True))

    def print_delta(
        self,
        msg: kvstore_types.Publication,
        ttl: bool,
        delta: bool,
        global_dbs: Dict,
    ):

        for key, value in msg.keyVals.items():
            if value.value is None:
                print(f"Traversal List: {msg.nodeIds}")
                self.print_publication_delta(
                    f"Key: {key}, ttl update",
                    [f"ttl: {value.ttl}, ttlVersion: {value.ttlVersion}"],
                    timestamp=True,
                )
                continue

            if key.startswith(Consts.ADJ_DB_MARKER):
                self.print_adj_delta(
                    key,
                    value,
                    delta,
                    global_dbs["adjs"],
                    global_dbs["publications"],
                )
                continue

            if key.startswith(Consts.PREFIX_DB_MARKER):
                self.print_prefix_delta(
                    key,
                    value,
                    delta,
                    global_dbs["prefixes"],
                    global_dbs["publications"],
                )
                continue

            print(f"Traversal List: {msg.nodeIds}")
            self.print_publication_delta(
                f"Key: {key} update",
                utils.sprint_pub_update(global_dbs["publications"], key, value),
                timestamp=True,
            )

    def print_prefix_delta(
        self,
        key: str,
        value: kvstore_types.Value,
        delta: bool,
        global_prefix_db: Dict,
        global_publication_db: Dict,
    ):
        prefix_db = serializer.deserialize_thrift_object(
            value.value,
            openr_types.PrefixDatabase,
        )
        if delta:
            lines = "\n".join(
                utils.sprint_prefixes_db_delta(global_prefix_db, prefix_db, key)
            )
        else:
            lines = utils.sprint_prefixes_db_full(prefix_db)

        if lines:
            self.print_publication_delta(
                f"{prefix_db.thisNodeName}'s prefixes",
                utils.sprint_pub_update(global_publication_db, key, value),
                lines,
                timestamp=True,
            )


        utils.update_global_prefix_db(global_prefix_db, prefix_db, key)

    def print_adj_delta(
        self,
        key: str,
        value: kvstore_types.Value,
        delta: bool,
        global_adj_db: Dict,
        global_publication_db: Dict,
    ):
        new_adj_db = serializer.deserialize_thrift_object(
            value.value, openr_types.AdjacencyDatabase
        )
        if delta:
            old_adj_db = global_adj_db.get(new_adj_db.thisNodeName, None)
            if old_adj_db is None:
                lines = (
                    f"ADJ_DB_ADDED: {new_adj_db.thisNodeName}\n"
                    + utils.sprint_adj_db_full(global_adj_db, new_adj_db, False)
                )

            else:
                lines = utils.sprint_adj_db_delta(new_adj_db, old_adj_db)
                lines = "\n".join(lines)
        else:
            lines = utils.sprint_adj_db_full(global_adj_db, new_adj_db, False)

        if lines:
            self.print_publication_delta(
                f"{new_adj_db.thisNodeName}'s adjacencies",
                utils.sprint_pub_update(global_publication_db, key, value),
                lines,
                timestamp=True,
            )


        utils.update_global_adj_db(global_adj_db, new_adj_db)

    def process_snapshot(self, resp: List[kvstore_types.Publication]) -> Dict:
        snapshots = {}
        print("Processing initial snapshots...")
        for pub in resp:
            global_dbs = bunch.Bunch(
                {
                    "prefixes": {},
                    "adjs": {},
                    "publications": {},  # map(key -> kvstore_types.Value)
                }
            )

            # Populate global_dbs
            global_dbs.prefixes = utils.build_global_prefix_db(pub)
            global_dbs.adjs = utils.build_global_adj_db(pub)
            for key, value in pub.keyVals.items():
                global_dbs.publications[key] = value
            snapshots[pub.area] = global_dbs
            print(f"Loaded {len(pub.keyVals)} initial key-values for area {pub.area}")
        print("Done.")
        return snapshots


class KvAllocationsListCmd(KvStoreCmdBase):
    def _run(
        self,
        client: OpenrCtrl.Client,
        *args,
        **kwargs,
    ) -> None:
        key = Consts.STATIC_PREFIX_ALLOC_PARAM_KEY
        resp = client.getKvStoreKeyVals([key])
        self.print_allocations(key, resp.keyVals)

    def print_allocations(
        self,
        key: str,
        keyVals: kvstore_types.KeyVals,
        area: Optional[str] = None,
    ) -> None:
        if key not in keyVals:
            print("Static allocation is not set in KvStore")
        else:
            area_str = (
                "" if area is None else f'Static prefix allocations in area "{area}"'
            )
            print(area_str)
            utils.print_allocations_table(
                getattr(
                    keyVals.get(key),
                    "value",
                    openr_types.StaticAllocation(nodePrefixes={}),
                )
            )


class AllocationsListCmd(KvAllocationsListCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        *args,
        **kwargs,
    ) -> None:
        if not self.area_feature:
            super()._run(client)
            return

        key = Consts.STATIC_PREFIX_ALLOC_PARAM_KEY
        for area in self.areas:
            resp = client.getKvStoreKeyValsArea([key], area)
            self.print_allocations(key, resp.keyVals, area)


class AllocationsSetCmd(SetKeyCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        node_name: str,
        prefix_str: str,
        *args,
        **kwargs,
    ) -> None:
        area = self.get_area_id()
        key = Consts.STATIC_PREFIX_ALLOC_PARAM_KEY

        # Retrieve previous allocation
        resp = None
        if area is None:
            resp = client.getKvStoreKeyVals([key])
        else:
            resp = client.getKvStoreKeyValsArea([key], area)
        allocs = None
        if key in resp.keyVals:
            allocs = serializer.deserialize_thrift_object(
                getattr(
                    resp.keyVals.get(key),
                    "value",
                    openr_types.StaticAllocation(nodePrefixes={}),
                ),
                openr_types.StaticAllocation,
            )
        else:
            allocs = openr_types.StaticAllocation(nodePrefixes={})

        # Return if there is no change
        prefix = ipnetwork.ip_str_to_prefix(prefix_str)
        if allocs.nodePrefixes.get(node_name) == prefix:
            print(
                f"No changes needed. {node_name}'s prefix is already set to {prefix_str}"
            )

            return

        # Update value in KvStore
        allocs.nodePrefixes[node_name] = prefix
        value = serializer.serialize_thrift_object(allocs)

        super(AllocationsSetCmd, self)._run(
            client, key, value, "breeze", None, Consts.CONST_TTL_INF
        )


class AllocationsUnsetCmd(SetKeyCmd):
    def _run(
        self,
        client: OpenrCtrl.Client,
        node_name: str,
        *args,
        **kwargs,
    ) -> None:
        area = self.get_area_id()
        key = Consts.STATIC_PREFIX_ALLOC_PARAM_KEY

        # Retrieve previous allocation
        resp = None
        if area is None:
            resp = client.getKvStoreKeyVals([key])
        else:
            resp = client.getKvStoreKeyValsArea([key], area)
        allocs = None
        if key in resp.keyVals:
            allocs = serializer.deserialize_thrift_object(
                getattr(
                    resp.keyVals.get(key),
                    "value",
                    openr_types.StaticAllocation(nodePrefixes={}),
                ),
                openr_types.StaticAllocation,
            )
        else:
            allocs = openr_types.StaticAllocation(
                nodePrefixes={node_name: network_types.IpPrefix()}
            )

        # Return if there need no change
        if node_name not in allocs.nodePrefixes:
            print(f"No changes needed. {node_name}'s prefix is not set")
            return

        # Update value in KvStore
        del allocs.nodePrefixes[node_name]
        value = serializer.serialize_thrift_object(allocs)

        super(AllocationsUnsetCmd, self)._run(
            client, key, value, "breeze", None, Consts.CONST_TTL_INF
        )


class SummaryCmd(KvStoreCmdBase):
    def _get_summary_stats_template(self, area: str = "") -> List[Dict[str, Any]]:
        if not area:
            title = "Global Summary Stats"
        else:
            title = f" Stats for Area {area}"
            area = f".{area}"
        return [
            {
                "title": title,
                "counters": [],
                "stats": [
                    ("  Sent Publications", f"kvstore.sent_publications{area}.count"),
                    ("  Sent KeyVals", f"kvstore.sent_key_vals{area}.sum"),
                    (
                        "  Rcvd Publications",
                        f"kvstore.received_publications{area}.count",
                    ),
                    ("  Rcvd KeyVals", f"kvstore.received_key_vals{area}.sum"),
                    ("  Updates KeyVals", f"kvstore.updated_key_vals{area}.sum"),
                ],
            },
        ]

    def _get_area_str(self) -> str:
        s = "s" if len(self.areas) != 1 else ""
        return f", {len(self.areas)} configured area{s}"

    def _get_bytes_str(self, bytes_count: int) -> str:
        if bytes_count < 1024:
            return f"{bytes_count} Bytes"
        elif bytes_count < 1024 * 1024:
            return "{:.2f}KB".format(bytes_count / 1024)
        else:
            return "{:.2f}MB".format(bytes_count / 1024 / 1024)

    def _get_peer_state_output(self, peersMap: kvstore_types.PeersMap) -> str:
        # form a list of peer state value for easy counting, for display
        states = [peer.state for peer in peersMap.values()]
        return (
            f" {states.count(kvstore_types.KvStorePeerState.INITIALIZED)} Initialized,"
            f" {states.count(kvstore_types.KvStorePeerState.SYNCING)} Syncing,"
            f" {states.count(kvstore_types.KvStorePeerState.IDLE)} Idle"
        )

    def _get_area_summary(self, s: kvstore_types.KvStoreAreaSummary) -> str:
        return (
            f"\n"
            f">> Area - {s.area}\n"
            f"   Peers: {len(s.peersMap)} Total - {self._get_peer_state_output(s.peersMap)}\n"
            f"   Database: {s.keyValsCount} KVs, {self._get_bytes_str(s.keyValsBytes)}"
        )

    def _get_global_summary(
        self, summaries: List[kvstore_types.KvStoreAreaSummary]
    ) -> kvstore_types.KvStoreAreaSummary:
        global_summary = kvstore_types.KvStoreAreaSummary()
        global_summary.area = f"ALL{self._get_area_str()}"
        # peersMap's type: Dict[str, kvstore_types.PeerSpec]
        global_summary.peersMap = {}
        # create a map of unique total peers for this node
        for s in summaries:
            for peer, peerSpec in s.peersMap.items():
                # if the same peer appears in multiple areas, and in a different state, then replace with lower state
                if (
                    peer not in global_summary.peersMap
                    or global_summary.peersMap[peer].state > peerSpec.state
                ):
                    global_summary.peersMap[peer] = peerSpec

        # count total key/value pairs across all areas
        global_summary.keyValsCount = sum(s.keyValsCount for s in summaries)
        # count total size (in bytes) of KvStoreDB across all areas
        global_summary.keyValsBytes = sum(s.keyValsBytes for s in summaries)
        return global_summary

    def _print_summarized_output(
        self,
        client: OpenrCtrl.Client,
        summaries: List[kvstore_types.KvStoreAreaSummary],
        input_areas: Set[str],
    ) -> None:
        allFlag: bool = False
        # if no area(s) filter specified in CLI, then get all configured areas
        if not input_areas:
            input_areas = set(self.areas)
            allFlag = True

        # include global summary, if no area(s) filter specified in CLI
        if allFlag:
            print(self._get_area_summary(self._get_global_summary(summaries)))
            self.print_stats(self._get_summary_stats_template(), client.getCounters())

        # build a list of per-area (filtered) summaries first
        for s in (s for s in summaries if s.area in input_areas):
            print(self._get_area_summary(s))
            self.print_stats(
                self._get_summary_stats_template(s.area), client.getCounters()
            )

    def _run(
        self,
        client: OpenrCtrl.Client,
        input_areas: Set[str],
        *args,
        **kwargs,
    ) -> None:
        areaSet = set(self.areas)
        # get per-area Summary list from KvStore for all areas
        summaries = client.getKvStoreAreaSummary(areaSet)
        # build summarized output from (filtered) summaries, and print it
        self._print_summarized_output(client, summaries, input_areas)
        print()


def ip_key(ip):
    net = ipaddress.ip_network(ip)
    return (net.version, net.network_address, net.prefixlen)


def convertTime(intTime):
    formatted_time = datetime.datetime.fromtimestamp(intTime / 1000)
    timezone = pytz.timezone("US/Pacific")
    formatted_time = timezone.localize(formatted_time)
    formatted_time = formatted_time.strftime("%Y-%m-%d %H:%M:%S.%f %Z")
    return formatted_time


class StreamSummaryCmd(KvStoreCmdBase):
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

        subscribers = await client.getSubscriberInfo(StreamSubscriberType.KVSTORE)

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
        print("KvStore stream summary information for subscribers\n")

        if not subscribers:
            print("No subscribers available")

        # Print the table body
        print(table)
