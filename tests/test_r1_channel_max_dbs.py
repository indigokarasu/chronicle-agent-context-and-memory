"""
Chronicle — R1: federation.channel_max_dbs config flows into FederatedChannel (§g3).

`FederatedChannel` used to cap the databases it searches at the hard-coded
module constant `MAX_DBS = 3`, no matter how many sources
`federation.local_dbs` declared or how cheap a federated read actually is
(~19ms measured). This proves the new `federation.channel_max_dbs` config key
actually reaches the channel, at both points that used to read the constant
directly: the provider list built at construction, and the default breadth
`query()` uses when a caller (retrieval.py) does not pass `max_dbs` itself.

Providers are fakes, not `LocalDBProvider`s pointed at real files: the channel
never needs to open a database to prove HOW MANY of them it is willing to ask,
so this stays fast and needs no filesystem or network I/O.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.config import Config
from engine.federated import MAX_DBS, FederatedChannel


class _FakeProvider:
    """Just enough surface for FederatedChannel.query(): availability + search."""

    def __init__(self, name):
        self.name = name
        self.db_path = "fake:%s" % name
        self.calls = 0

    def is_available(self):
        return True

    def search(self, tokens, owner=None, principal=None, max_tables=None, max_rows=None):
        self.calls += 1
        return []


def _channel(n_providers, **federation_overrides):
    cfg = Config({"federation": federation_overrides} if federation_overrides else {})
    providers = [_FakeProvider("db%d" % i) for i in range(n_providers)]
    return FederatedChannel(cfg, providers=providers), providers


class TestChannelMaxDbsConfig(unittest.TestCase):
    """Declaration-time breadth: how many providers the channel even keeps."""

    def test_default_caps_providers_at_module_constant(self):
        channel, _ = _channel(5)
        self.assertEqual(channel.channel_max_dbs, MAX_DBS)
        self.assertEqual(len(channel.providers), 3)

    def test_config_value_raises_provider_count(self):
        channel, _ = _channel(5, channel_max_dbs=5)
        self.assertEqual(channel.channel_max_dbs, 5)
        self.assertEqual(len(channel.providers), 5)

    def test_config_value_can_also_lower_provider_count(self):
        channel, _ = _channel(5, channel_max_dbs=1)
        self.assertEqual(len(channel.providers), 1)

    def test_no_cfg_falls_back_to_max_dbs_constant(self):
        providers = [_FakeProvider("db%d" % i) for i in range(5)]
        channel = FederatedChannel(cfg=None, providers=providers)
        self.assertEqual(channel.channel_max_dbs, MAX_DBS)
        self.assertEqual(len(channel.providers), 3)


class TestQueryHonoursConfiguredBreadth(unittest.TestCase):
    """Query-time breadth: how many providers actually get asked (3 vs 5 seen)."""

    def test_query_asks_only_three_providers_by_default(self):
        channel, providers = _channel(5)
        channel.query(["token"], principal="u", owner="u")
        asked = sum(1 for p in providers if p.calls)
        self.assertEqual(asked, 3)

    def test_query_asks_five_providers_when_configured(self):
        channel, providers = _channel(5, channel_max_dbs=5)
        channel.query(["token"], principal="u", owner="u")
        asked = sum(1 for p in providers if p.calls)
        self.assertEqual(asked, 5)


if __name__ == "__main__":
    unittest.main()
