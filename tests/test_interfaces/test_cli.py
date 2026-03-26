"""Tests für CLI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from mampok.interfaces.cli import _expand_relative_lifetime, _mamplan_expiry_info


# ---------------------------------------------------------------------------
# TestMamplanExpiryInfo — Feature E helper
# ---------------------------------------------------------------------------


class TestMamplanExpiryInfo:
    """Tests für _mamplan_expiry_info Hilfsfunktion."""

    def _make_mamplan(self, status: bool, lifetime: str, project_id: str = "proj") -> MagicMock:
        mp = MagicMock()
        mp.data = {
            "project": {"project_id": project_id},
            "deployment": {"status": status, "lifetime": lifetime},
        }
        return mp

    def test_returns_dict_for_active_expiring_soon(self):
        future = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        mp = self._make_mamplan(True, future, "proj-x")
        result = _mamplan_expiry_info(mp, timedelta(days=7))
        assert result is not None
        assert result["project_id"] == "proj-x"
        assert "lifetime" in result
        assert "days_remaining" in result

    def test_returns_none_for_inactive(self):
        future = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        mp = self._make_mamplan(False, future)
        assert _mamplan_expiry_info(mp, timedelta(days=7)) is None

    def test_returns_none_for_already_expired(self):
        past = "2020-01-01T00:00:00+00:00"
        mp = self._make_mamplan(True, past)
        assert _mamplan_expiry_info(mp, timedelta(days=7)) is None

    def test_returns_none_when_beyond_window(self):
        far_future = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        mp = self._make_mamplan(True, far_future)
        assert _mamplan_expiry_info(mp, timedelta(days=7)) is None

    def test_days_remaining_correct(self):
        future = (datetime.now(timezone.utc) + timedelta(days=4, hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        mp = self._make_mamplan(True, future)
        result = _mamplan_expiry_info(mp, timedelta(days=7))
        assert result is not None
        assert result["days_remaining"] == 4

    def test_timezone_naive_handled(self):
        future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
        mp = self._make_mamplan(True, future)
        result = _mamplan_expiry_info(mp, timedelta(days=7))
        assert result is not None


# ---------------------------------------------------------------------------
# TestExpandRelativeLifetime — Feature F helper
# ---------------------------------------------------------------------------


class TestExpandRelativeLifetime:
    """Tests für _expand_relative_lifetime Hilfsfunktion."""

    def _make_mamplan(self, lifetime: str) -> MagicMock:
        mp = MagicMock()
        mp.data = {"deployment": {"lifetime": lifetime}}
        return mp

    def test_expands_days_offset(self):
        base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        mp = self._make_mamplan("2026-01-01T00:00:00Z")
        result = _expand_relative_lifetime(["deployment:lifetime:+14d"], mp)
        assert len(result) == 1
        dt = datetime.fromisoformat(result[0].split(":", 2)[2].replace("Z", "+00:00"))
        assert dt == base + timedelta(days=14)

    def test_expands_weeks_offset(self):
        base = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        mp = self._make_mamplan("2026-03-01T00:00:00Z")
        result = _expand_relative_lifetime(["deployment:lifetime:+2w"], mp)
        dt = datetime.fromisoformat(result[0].split(":", 2)[2].replace("Z", "+00:00"))
        assert dt == base + timedelta(weeks=2)

    def test_expands_months_offset(self):
        base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        mp = self._make_mamplan("2026-01-01T00:00:00Z")
        result = _expand_relative_lifetime(["deployment:lifetime:+1m"], mp)
        dt = datetime.fromisoformat(result[0].split(":", 2)[2].replace("Z", "+00:00"))
        assert dt == base + timedelta(days=30)

    def test_non_lifetime_token_passes_through(self):
        mp = self._make_mamplan("2026-01-01T00:00:00Z")
        tokens = ["project:project_id:new-id", "deployment:cluster:BN"]
        result = _expand_relative_lifetime(tokens, mp)
        assert result == tokens

    def test_absolute_lifetime_passes_through(self):
        mp = self._make_mamplan("2026-01-01T00:00:00Z")
        token = "deployment:lifetime:2027-06-01T00:00:00Z"
        result = _expand_relative_lifetime([token], mp)
        assert result == [token]

    def test_mixed_list_only_transforms_lifetime_token(self):
        mp = self._make_mamplan("2026-01-01T00:00:00Z")
        tokens = ["project:project_id:foo", "deployment:lifetime:+7d", "deployment:cluster:BN"]
        result = _expand_relative_lifetime(tokens, mp)
        assert result[0] == "project:project_id:foo"
        assert result[1].startswith("deployment:lifetime:")
        assert "+7d" not in result[1]  # was expanded to ISO
        assert result[2] == "deployment:cluster:BN"

    def test_offset_added_to_existing_lifetime_not_now(self):
        """The +Nd offset is added to the mamplan's existing lifetime, not to now()."""
        fixed_base = "2026-01-01T00:00:00Z"
        mp = self._make_mamplan(fixed_base)
        result = _expand_relative_lifetime(["deployment:lifetime:+10d"], mp)
        dt = datetime.fromisoformat(result[0].split(":", 2)[2].replace("Z", "+00:00"))
        expected = datetime(2026, 1, 11, 0, 0, 0, tzinfo=timezone.utc)
        assert dt == expected
