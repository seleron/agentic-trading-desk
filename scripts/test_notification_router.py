#!/usr/bin/env python3
"""
test_notification_router.py
===========================
Tests for notification router — classification, Telegram message building,
quiet hours logic, EOD summary, and routing with trade plan integration.

Run with:  python3 scripts/test_notification_router.py
           or: pytest scripts/test_notification_router.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from notification_router import (
    _build_telegram_message,
    _build_eod_summary,
    _is_in_quiet_hours,
    classify_score,
    route_notifications,
)
import notification_router


class TestClassifyScore(unittest.TestCase):
    """Test score-to-tier classification."""

    def test_strong_buy_threshold(self):
        n = classify_score(85, "EREGL", ["trend up"])
        self.assertEqual(n.tier, "strong_buy")
        self.assertTrue(n.action_required)

    def test_watchlist_range(self):
        n = classify_score(70, "EREGL", [])
        self.assertEqual(n.tier, "watchlist")
        self.assertFalse(n.action_required)

    def test_below_threshold_silent(self):
        n = classify_score(69, "EREGL", [])
        self.assertEqual(n.tier, "no_trade")
        self.assertFalse(n.action_required)

    def test_strong_buy_high_score(self):
        n = classify_score(100, "EREGL", ["all signals aligned"])
        self.assertEqual(n.tier, "strong_buy")


class TestTelegramMessageBuilder(unittest.TestCase):
    """Test Telegram-formatted message construction."""

    def test_strong_buy_full_details(self):
        msg = _build_telegram_message(
            "strong_buy", "EREGL", 92,
            ["EMA cross bullish", "RSI rising", "MACD divergence"],
            {"entry_price": 45.0, "stop_loss": 43.0, "targets": [{"price": 50.0, "reason": "R1"}]},
        )
        self.assertIn("STRONG BUY", msg)
        self.assertIn("92/100", msg)
        self.assertIn("45.0", msg)
        self.assertIn("43.0", msg)
        self.assertIn("50.0", msg)

    def test_watchlist_message(self):
        msg = _build_telegram_message(
            "watchlist", "TUPRS", 78, ["monitor"],
        )
        self.assertIn("WATCHLIST ADD", msg)
        self.assertIn("78/100", msg)

    def test_no_trade_returns_empty(self):
        msg = _build_telegram_message(
            "no_trade", "EREGL", 65, [],
        )
        self.assertEqual(msg, "")


class TestQuietHours(unittest.TestCase):
    """Test quiet hours logic."""

    def test_straightforward_range(self):
        # Patch datetime.now().hour to simulate 2am (quiet)
        mock_dt = unittest.mock.MagicMock()
        mock_dt.now.return_value.hour = 2
        with unittest.mock.patch.object(notification_router, "datetime", mock_dt):
            self.assertTrue(_is_in_quiet_hours(23, 6))

    def test_outside_quiet_hours(self):
        mock_dt = unittest.mock.MagicMock()
        mock_dt.now.return_value.hour = 14
        with unittest.mock.patch.object(notification_router, "datetime", mock_dt):
            self.assertFalse(_is_in_quiet_hours(23, 6))


class TestEODSummary(unittest.TestCase):
    """Test EOD summary message generation."""

    def test_eod_summary_content(self):
        report = {
            "wins": 3,
            "losses": 1,
            "open_positions": 0,
            "win_rate": 75.0,
            "total_pnl_pct": 4.2,
        }
        notifs = [
            {"tier": "strong_buy"},
            {"tier": "watchlist"},
        ]
        msg = _build_eod_summary(report, notifs)
        self.assertIn("EOD Summary", msg)
        self.assertIn("75.0%", msg)
        self.assertIn("4.20%", msg)


class TestRouteNotifications(unittest.TestCase):
    """Test full routing with dedup and trade plan integration."""

    def test_basic_routing(self):
        scores = [
            {"score": 92, "symbol": "EREGL", "rationale": ["strong trend"]},
            {"score": 75, "symbol": "TUPRS", "rationale": []},
            {"score": 60, "symbol": "ASELS", "rationale": []},
        ]
        selection = {"market_bias": "positive", "no_trade_day": False, "avg_score_all_stocks": 75}

        notifs = route_notifications(scores, selection)
        tiers = [n["tier"] for n in notifs]
        self.assertIn("strong_buy", tiers)
        self.assertIn("watchlist", tiers)
        self.assertNotIn("no_trade", tiers)

    def test_deduplication(self):
        scores = [
            {"score": 92, "symbol": "EREGL", "rationale": []},
            {"score": 88, "symbol": "EREGL", "rationale": []},  # duplicate symbol
        ]
        selection = {}
        notifs = route_notifications(scores, selection)
        strong_buys = [n for n in notifs if n["tier"] == "strong_buy"]
        self.assertEqual(len(strong_buys), 1)

    def test_telegram_integration(self):
        scores = [{"score": 92, "symbol": "EREGL", "rationale": ["test"]}]
        selection = {}
        telegram_cfg = {"api_token": "fake:token", "chat_id": "123456"}

        with patch("notification_router._send_telegram_message") as mock_send:
            mock_send.return_value = True
            notifs = route_notifications(
                scores, selection,
                telegram_config=telegram_cfg,
                trade_plans=[{"symbol": "EREGL", "entry_price": 45.0}],
            )
            mock_send.assert_called_once()

    def test_quiet_hours_skips_telegram(self):
        scores = [{"score": 92, "symbol": "EREGL", "rationale": []}]
        selection = {}
        telegram_cfg = {"api_token": "fake:token", "chat_id": "123456"}

        with patch("notification_router._is_in_quiet_hours", return_value=True):
            with patch("notification_router._send_telegram_message") as mock_send:
                notifs = route_notifications(
                    scores, selection,
                    telegram_config=telegram_cfg,
                )
                # Notification still in JSON output but Telegram skipped
                self.assertEqual(len(notifs), 1)
                mock_send.assert_not_called()

    def test_no_telegram_when_unconfigured(self):
        scores = [{"score": 92, "symbol": "EREGL", "rationale": []}]
        selection = {}

        with patch("notification_router._send_telegram_message") as mock_send:
            notifs = route_notifications(scores, selection)
            self.assertEqual(len(notifs), 1)
            mock_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
