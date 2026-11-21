"""RSS decisions run without loading NoneBot, SQLAlchemy or network clients."""

from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch


class RSSStateMachineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).resolve().parents[1] / "nsy/plugins/rssget/state_machines.py"

    def decisions(self):
        self.assertTrue(self.path.is_file(), "RSS transition decisions need a standalone pure module")
        name = "rss_pure_state_machine_tests"
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(name, self.path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        return sys.modules[name]

    def test_first_healthy_observation_queues_heartbeat_without_change_event(self):
        sm = self.decisions()
        now = datetime(2026, 11, 21, 12)
        result = sm.source_health_transition(None, True, now, notify=True)
        self.assertFalse(result.changed)
        self.assertTrue(result.enqueue_notice)
        self.assertTrue(result.available)
        self.assertEqual(result.observed_at, now)
        self.assertIsNone(result.retry_at)

    def test_initial_outage_and_recovery_emit_changes_but_repeated_outage_does_not(self):
        sm = self.decisions()
        now = datetime(2026, 11, 21, 12)
        first = sm.source_health_transition(None, False, now, cooldown=1200, notify=True)
        repeated = sm.source_health_transition(False, False, now, cooldown=3600, notify=True)
        recovered = sm.source_health_transition(False, True, now, cooldown=3600, notify=True)
        self.assertTrue(first.changed)
        self.assertEqual(first.retry_at, datetime(2026, 11, 21, 12, 20))
        self.assertFalse(repeated.changed)
        self.assertTrue(repeated.enqueue_notice)
        self.assertEqual(repeated.retry_at, datetime(2026, 11, 21, 13))
        self.assertTrue(recovered.changed)
        self.assertIsNone(recovered.retry_at)
        self.assertFalse(sm.source_health_transition(True, True, now, notify=False).enqueue_notice)

    def test_rate_limit_stops_source_round_immediately_and_keeps_longest_retry(self):
        sm = self.decisions()
        first = sm.source_round_transition(sm.SourceRound(), sm.SourceOutcome.UNAVAILABLE,
                                           retry_after=3600, threshold=3, cooldown=600)
        limited = sm.source_round_transition(first.state, sm.SourceOutcome.RATE_LIMITED,
                                             retry_after=60, threshold=3, cooldown=600)
        self.assertIsNone(first.observation)
        self.assertTrue(limited.state.paused)
        self.assertIs(limited.observation, sm.SourceObservation.UNAVAILABLE)
        self.assertEqual(limited.cooldown, 3600)
        self.assertIsNone(sm.finish_source_round(limited.state, cooldown=600).observation)

    def test_account_error_breaks_failure_streak_without_proving_global_outage(self):
        sm = self.decisions()
        account = sm.source_round_transition(sm.SourceRound(), sm.SourceOutcome.ACCOUNT_FAILURE,
                                             threshold=2, cooldown=600)
        self.assertFalse(account.state.paused)
        self.assertIsNone(sm.finish_source_round(account.state, cooldown=600).observation)
        first = sm.source_round_transition(account.state, sm.SourceOutcome.UNAVAILABLE,
                                           threshold=2, cooldown=600)
        reset = sm.source_round_transition(first.state, sm.SourceOutcome.ACCOUNT_FAILURE,
                                           threshold=2, cooldown=600)
        next_failure = sm.source_round_transition(reset.state, sm.SourceOutcome.UNAVAILABLE,
                                                  threshold=2, cooldown=600)
        self.assertFalse(next_failure.state.paused)
        self.assertIs(sm.finish_source_round(next_failure.state, cooldown=600).observation,
                      sm.SourceObservation.UNAVAILABLE)

    def test_threshold_and_round_end_both_preserve_longest_retry_after(self):
        sm = self.decisions()
        first = sm.source_round_transition(sm.SourceRound(), sm.SourceOutcome.UNAVAILABLE,
                                           retry_after=3600, threshold=2, cooldown=600)
        ended = sm.finish_source_round(first.state, cooldown=600)
        self.assertIs(ended.observation, sm.SourceObservation.UNAVAILABLE)
        self.assertEqual(ended.cooldown, 3600)
        stopped = sm.source_round_transition(first.state, sm.SourceOutcome.UNAVAILABLE,
                                             threshold=2, cooldown=600)
        self.assertTrue(stopped.state.paused)
        self.assertEqual(stopped.cooldown, 3600)

    def test_success_observes_once_and_is_not_overridden_by_one_failed_account(self):
        sm = self.decisions()
        success = sm.source_round_transition(sm.SourceRound(), sm.SourceOutcome.AVAILABLE,
                                             threshold=3, cooldown=600)
        self.assertIs(success.observation, sm.SourceObservation.AVAILABLE)
        again = sm.source_round_transition(success.state, sm.SourceOutcome.AVAILABLE,
                                           threshold=3, cooldown=600)
        failed = sm.source_round_transition(again.state, sm.SourceOutcome.UNAVAILABLE,
                                            threshold=3, cooldown=600)
        self.assertIsNone(again.observation)
        self.assertIsNone(sm.finish_source_round(failed.state, cooldown=600).observation)

    def test_paused_round_has_no_further_observations(self):
        sm = self.decisions()
        stopped = sm.source_round_transition(sm.SourceRound(), sm.SourceOutcome.RATE_LIMITED,
                                             threshold=3, cooldown=600)
        ignored = sm.source_round_transition(stopped.state, sm.SourceOutcome.AVAILABLE,
                                             threshold=3, cooldown=600)
        self.assertEqual(ignored.state, stopped.state)
        self.assertIsNone(ignored.observation)

    def test_ingest_retry_keeps_pending_work_and_caps_exponential_delay(self):
        sm = self.decisions()
        now = datetime(2026, 11, 21, 12)
        for attempts, seconds in ((0, 30), (1, 60), (2, 120), (6, 1920), (7, 3600), (10000, 3600)):
            with self.subTest(attempts=attempts):
                result = sm.ingest_retry(attempts, now)
                self.assertEqual(result.attempts, attempts + 1)
                self.assertEqual(result.next_retry_at, now + timedelta(seconds=seconds))

    def test_write_outcomes_keep_legacy_success_semantics_for_superseded_versions(self):
        sm = self.decisions()
        for outcome, expected in ((sm.WriteOutcome.COMMITTED, True),
                                  (sm.WriteOutcome.SUPERSEDED, True),
                                  (sm.WriteOutcome.RETRY_PENDING, False)):
            with self.subTest(outcome=outcome):
                self.assertIs(outcome.success, expected)
                self.assertIs(bool(outcome), expected)

    def test_delivery_decision_distinguishes_each_silent_reason(self):
        sm = self.decisions()
        cases = (
            ({}, sm.DeliveryDecision.SEND),
            ({"already_delivered": True}, sm.DeliveryDecision.ALREADY_DELIVERED),
            ({"startup_baseline": True}, sm.DeliveryDecision.STARTUP),
            ({"in_window": False}, sm.DeliveryDecision.WINDOW),
            ({"is_self_repost": True, "allow_self_reposts": False}, sm.DeliveryDecision.FILTERED),
            ({"is_repost": True, "allow_reposts": False}, sm.DeliveryDecision.FILTERED),
            ({"is_self_repost": True, "is_repost": True, "allow_self_reposts": True,
              "allow_reposts": False}, sm.DeliveryDecision.SEND),
        )
        for inputs, expected in cases:
            with self.subTest(inputs=inputs):
                self.assertIs(sm.delivery_decision(**inputs), expected)


class RSSSourceFailureClassificationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        from rss_test_support import load_rss_plugin

        cls.test_root = tempfile.TemporaryDirectory(prefix="nsybot-rss-states-")
        cls.rss = load_rss_plugin(cls.test_root.name)
        from nsy.plugins.rssget import functions

        cls.functions = functions

    @classmethod
    def tearDownClass(cls):
        cls.test_root.cleanup()

    async def test_account_resource_budget_failure_does_not_mark_platform_offline(self):
        responses = [
            {"entries": [], "error": "FeedTooLarge", "resource_limited": True},
            {"entries": [], "error": "unavailable", "status_code": 503},
        ]
        with patch.object(self.functions.config, "rsshub_host", "https://primary.invalid"), patch.object(
            self.functions.config, "rsshub_host_back", ["https://backup.invalid"],
        ), patch.object(self.functions, "fetch_feed", AsyncMock(side_effect=responses)):
            with self.assertRaises(self.rss.FeedUnavailable) as failed:
                await self.functions.rss_get()._fetch_user_feed("account", "/twitter/user/", "twitter")
        self.assertFalse(failed.exception.global_failure)


if __name__ == "__main__":
    unittest.main()
