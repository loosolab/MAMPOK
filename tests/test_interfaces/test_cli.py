"""Tests for CLI."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer

from mampok.interfaces.cli import CLI, _confirm_mamplans, _expand_relative_lifetime, _load_config, _mamplan_expiry_info, _parse_edit_args, _warn_unknown_selection_keys, apply_selection, load_mamplans
from mampok.mamplan.base import ListAdd, ListRemove, ListReplace
from mampok.mamplan.mamplan import Mamplan
from mampok.mamplan.shmamplan import SHMamplan

MINIMAL_CONFIG = {
    "cluster": {
        "MY_CLUSTER": {
            "host": "cluster.example.com",
            "namespace": "mampok",
            "kubeconfig_path": "/app/my_kube_config",
        }
    },
    "s3": {
        "endpoint": "https://s3.example.com",
        "access_key": "mampok-service",
        "secret_key": "secret123",
        "secretname": "mampok-secrets",
    },
    "mamplates_path": "/app/mamplates",
    "lifetime_days": 10,
    "mampok_version": ">=3.0.0",
}


# ---------------------------------------------------------------------------
# TestLoadConfig — friendly config-loading errors (Issue 1)
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """_load_config() must turn config-loading exceptions into readable errors."""

    def test_loads_valid_config(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(MINIMAL_CONFIG))

        cfg = _load_config(config_path)

        assert "MY_CLUSTER" in cfg.clusters

    def test_missing_file_exits_with_message(self, tmp_path, capsys):
        config_path = tmp_path / "does-not-exist.json"

        with pytest.raises(typer.Exit) as exc_info:
            _load_config(config_path)

        assert exc_info.value.exit_code == 1
        assert "not found" in capsys.readouterr().err

    def test_invalid_json_exits_with_message(self, tmp_path, capsys):
        config_path = tmp_path / "config.yml"
        config_path.write_text("cluster:\n  MY_CLUSTER:\n    host: example.com\n")

        with pytest.raises(typer.Exit) as exc_info:
            _load_config(config_path)

        assert exc_info.value.exit_code == 1
        err = capsys.readouterr().err
        assert "not valid JSON" in err
        assert "Only JSON" in err

    def test_schema_violation_exits_with_message(self, tmp_path, capsys):
        broken = {k: v for k, v in MINIMAL_CONFIG.items() if k != "cluster"}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(broken))

        with pytest.raises(typer.Exit) as exc_info:
            _load_config(config_path)

        assert exc_info.value.exit_code == 1
        assert "Config file invalid" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# TestMamplanExpiryInfo — Feature E helper
# ---------------------------------------------------------------------------


class TestMamplanExpiryInfo:
    """Tests for the _mamplan_expiry_info helper function."""

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
    """Tests for the _expand_relative_lifetime helper function."""

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


# ---------------------------------------------------------------------------
# TestCLIRedeployStopFirst — Feature I9: Stop vor Redeploy
# ---------------------------------------------------------------------------


class TestCLIRedeployStopFirst:
    """CLI.redeploy führt Stop immer vollständig aus, bevor Deploy beginnt."""

    def _make_mamplan(self, project_id: str = "test-proj", tmp_path: Path | None = None) -> MagicMock:
        mp = MagicMock()
        mp.data = {"project": {"project_id": project_id}, "deployment": {"url": ""}}
        mp.source_path = (tmp_path / f"{project_id}.yaml") if tmp_path else Path("/tmp/test.yaml")
        return mp

    def test_stop_generator_fully_consumed_before_deploy(self, tmp_path, capsys):
        """stop()-Generator wird vollständig iteriert bevor deploy() aufgerufen wird."""
        mamplan = self._make_mamplan(tmp_path=tmp_path)
        call_log: list[str] = []

        def stop_gen(_config):
            call_log.append("stop_start")
            yield {"stage": "k8s_delete", "resource": "Deployment/test-proj"}
            call_log.append("stop_end")

        def deploy_gen(_config, timeout=300, reupload=False):
            call_log.append("deploy_start")
            yield {"stage": "done"}
            call_log.append("deploy_end")

        mock_mampok = MagicMock()
        mock_mampok.stop.side_effect = stop_gen
        mock_mampok.deploy.side_effect = deploy_gen

        cli = CLI(MagicMock())

        with patch.object(cli, "_load", return_value=([mamplan], {})), \
             patch("mampok.interfaces.cli.apply_selection", return_value=[mamplan]), \
             patch("mampok.interfaces.cli._confirm_mamplans", return_value=True), \
             patch("mampok.interfaces.cli.create_mampok_instance", return_value=mock_mampok):
            cli.redeploy(tmp_path / "mamplan.yaml", throw_error=True)

        assert call_log == ["stop_start", "stop_end", "deploy_start", "deploy_end"]
        assert mamplan.write.call_count == 2

    def test_stop_output_before_redeploy_output(self, tmp_path, capsys):
        """'Stopped: ...' erscheint in der Ausgabe vor 'Redeployed: ...'."""
        mamplan = self._make_mamplan(tmp_path=tmp_path)

        def stop_gen(_config):
            yield {"stage": "k8s_delete", "resource": "Deployment/test-proj"}

        def deploy_gen(_config, timeout=300, reupload=False):
            yield {"stage": "done"}

        mock_mampok = MagicMock()
        mock_mampok.stop.side_effect = stop_gen
        mock_mampok.deploy.side_effect = deploy_gen

        cli = CLI(MagicMock())

        with patch.object(cli, "_load", return_value=([mamplan], {})), \
             patch("mampok.interfaces.cli.apply_selection", return_value=[mamplan]), \
             patch("mampok.interfaces.cli._confirm_mamplans", return_value=True), \
             patch("mampok.interfaces.cli.create_mampok_instance", return_value=mock_mampok):
            cli.redeploy(tmp_path / "mamplan.yaml", throw_error=True)

        out = capsys.readouterr().out
        assert "deleted: Deployment/test-proj" in out
        assert "Stopped: test-proj" in out
        assert "Redeployed: test-proj" in out
        assert out.index("Stopped: test-proj") < out.index("Redeployed: test-proj")


# ---------------------------------------------------------------------------
# TestCLIUpdateAuthOnlyDeployed — update-auth wirkt nur auf deployte Mamplans
# ---------------------------------------------------------------------------


class TestCLIUpdateAuthOnlyDeployed:
    """CLI.update_auth aktualisiert nur Mamplans mit deployment.status=True."""

    def _make_mamplan(self, project_id: str, deployment: dict) -> MagicMock:
        mp = MagicMock()
        mp.data = {"project": {"project_id": project_id}, "deployment": deployment}
        return mp

    def test_only_deployed_mamplan_is_updated(self, tmp_path):
        deployed = self._make_mamplan("deployed-proj", {"status": True})
        undeployed = self._make_mamplan("undeployed-proj", {"status": False})

        mock_mampok = MagicMock()
        mock_mampok.update_auth_secret.return_value = "https://example.com/token"

        cli = CLI(MagicMock())

        with patch.object(cli, "_load", return_value=([deployed, undeployed], {})), \
             patch("mampok.interfaces.cli.apply_selection", return_value=[deployed, undeployed]), \
             patch("mampok.interfaces.cli._confirm_mamplans", return_value=True) as mock_confirm, \
             patch("mampok.interfaces.cli.create_mampok_instance", return_value=mock_mampok):
            cli.update_auth(tmp_path / "mamplan.yaml", yes=True)

        mock_mampok.update_auth_secret.assert_called_once_with(cli.config)
        assert mock_confirm.call_args[0][0] == [deployed]

    def test_no_deployed_mamplans_updates_nothing(self, tmp_path, capsys):
        undeployed = self._make_mamplan("undeployed-proj", {"status": False})
        mock_mampok = MagicMock()
        cli = CLI(MagicMock())

        with patch.object(cli, "_load", return_value=([undeployed], {})), \
             patch("mampok.interfaces.cli.apply_selection", return_value=[undeployed]), \
             patch("mampok.interfaces.cli.create_mampok_instance", return_value=mock_mampok):
            cli.update_auth(tmp_path / "mamplan.yaml", yes=True)

        mock_mampok.update_auth_secret.assert_not_called()
        assert "No Mamplans match" in capsys.readouterr().out

    def test_missing_status_defaults_to_not_deployed(self, tmp_path):
        mp = self._make_mamplan("no-status-proj", {})
        mock_mampok = MagicMock()
        cli = CLI(MagicMock())

        with patch.object(cli, "_load", return_value=([mp], {})), \
             patch("mampok.interfaces.cli.apply_selection", return_value=[mp]), \
             patch("mampok.interfaces.cli.create_mampok_instance", return_value=mock_mampok):
            cli.update_auth(tmp_path / "mamplan.yaml", yes=True)

        mock_mampok.update_auth_secret.assert_not_called()


class TestParseEditArgs:
    def test_scalar_token(self):
        result = _parse_edit_args(["service:owner:alice"])
        assert result == [("service__owner", "alice")]

    def test_list_add_token(self):
        result = _parse_edit_args(["service:analyst:+:alice"])
        assert len(result) == 1
        key, value = result[0]
        assert key == "service__analyst"
        assert isinstance(value, ListAdd)
        assert value.item == "alice"

    def test_list_remove_token(self):
        result = _parse_edit_args(["service:analyst:-:jdoe"])
        key, value = result[0]
        assert key == "service__analyst"
        assert isinstance(value, ListRemove)
        assert value.item == "jdoe"

    def test_list_replace_token(self):
        result = _parse_edit_args(["service:analyst:old_name%new_name"])
        key, value = result[0]
        assert key == "service__analyst"
        assert isinstance(value, ListReplace)
        assert value.old == "old_name"
        assert value.new == "new_name"

    def test_mixed_tokens(self):
        result = _parse_edit_args([
            "service:owner:alice",
            "service:analyst:+:bob",
        ])
        assert result[0] == ("service__owner", "alice")
        assert result[1][0] == "service__analyst"
        assert isinstance(result[1][1], ListAdd)

    def test_invalid_token_raises(self):
        with pytest.raises(ValueError, match="Invalid edit token"):
            _parse_edit_args(["badtoken"])

    def test_value_with_colon_in_scalar(self):
        result = _parse_edit_args(["deployment:url:https://example.com"])
        assert result == [("deployment__url", "https://example.com")]

    def test_new_value_with_colon_in_replace(self):
        result = _parse_edit_args(["service:analyst:old%new:with:colons"])
        key, op = result[0]
        assert key == "service__analyst"
        assert isinstance(op, ListReplace)
        assert op.old == "old"
        assert op.new == "new:with:colons"

    def test_duplicate_key_tokens_preserved(self):
        result = _parse_edit_args([
            "service:analyst:+:alice",
            "service:analyst:+:bob",
            "service:analyst:+:carol",
        ])
        assert [key for key, _ in result] == ["service__analyst"] * 3
        assert [value.item for _, value in result] == ["alice", "bob", "carol"]


class TestApplySelection:
    def _make_mamplan(self, data: dict) -> MagicMock:
        mp = MagicMock()
        mp.data = data
        return mp

    def test_scalar_exact_match(self):
        mp = self._make_mamplan({"service": {"owner": "alice"}})
        assert apply_selection([mp], ["service:owner:alice"], []) == [mp]

    def test_scalar_no_match(self):
        mp = self._make_mamplan({"service": {"owner": "alice"}})
        assert apply_selection([mp], ["service:owner:bob"], []) == []

    def test_list_field_matches_element(self):
        mp = self._make_mamplan({"service": {"analyst": ["alice", "bob"]}})
        assert apply_selection([mp], ["service:analyst:alice"], []) == [mp]

    def test_list_field_no_match(self):
        mp = self._make_mamplan({"service": {"analyst": ["alice", "bob"]}})
        assert apply_selection([mp], ["service:analyst:carol"], []) == []

    def test_list_field_does_not_match_full_repr(self):
        """Exact match on a list field must NOT match the str() representation."""
        mp = self._make_mamplan({"service": {"analyst": ["alice"]}})
        assert apply_selection([mp], ["service:analyst:['alice']"], []) == []

    def test_regex_matches_list_element(self):
        mp = self._make_mamplan({"service": {"analyst": ["alice", "bob"]}})
        assert apply_selection([mp], [], ["service:analyst:ali"]) == [mp]


class TestWarnUnknownSelectionKeys:
    def _make_mamplan(self, data: dict) -> MagicMock:
        mp = MagicMock()
        mp.data = data
        return mp

    def test_errors_on_unknown_key(self, capsys):
        mp = self._make_mamplan({"service": {"owner": "alice", "analyst": ["bob"]}})
        result = _warn_unknown_selection_keys(mp, ["service:analzst:bob"])
        err = capsys.readouterr().err
        assert result is True
        assert "Unknown field" in err
        assert "analzst" in err

    def test_shows_valid_fields(self, capsys):
        mp = self._make_mamplan({"service": {"owner": "alice", "analyst": ["bob"]}})
        _warn_unknown_selection_keys(mp, ["service:analzst:bob"])
        err = capsys.readouterr().err
        assert "analyst" in err
        assert "owner" in err

    def test_no_error_for_valid_key(self, capsys):
        mp = self._make_mamplan({"service": {"analyst": ["bob"]}})
        result = _warn_unknown_selection_keys(mp, ["service:analyst:bob"])
        err = capsys.readouterr().err
        assert result is False
        assert err == ""

    def test_errors_on_unknown_section(self, capsys):
        mp = self._make_mamplan({"service": {"owner": "alice"}})
        result = _warn_unknown_selection_keys(mp, ["typo:owner:alice"])
        err = capsys.readouterr().err
        assert result is True
        assert "Unknown field" in err
        assert "typo" in err

    def test_apply_selection_exits_on_bad_key(self, capsys):
        import typer
        mp = self._make_mamplan({"service": {"owner": "alice", "analyst": ["bob"]}})
        with pytest.raises(typer.Exit) as exc_info:
            apply_selection([mp], ["service:analzst:bob"], [])
        assert exc_info.value.exit_code == 1
        err = capsys.readouterr().err
        assert "Unknown field" in err


class TestConfirmMamplans:
    def test_empty_list_returns_false(self, capsys):
        result = _confirm_mamplans([], "edited")
        assert result is False

    def test_empty_list_prints_message(self, capsys):
        _confirm_mamplans([], "edited")
        out = capsys.readouterr().out
        assert "No Mamplans match" in out


# ---------------------------------------------------------------------------
# TestLoadMamplans — directory scan must pick up both Mamplan and SHMamplan
# ---------------------------------------------------------------------------


MINIMAL_MAMPLAN = {
    "project": {
        "project_id": "my-project",
        "tool": "cellxgene",
        "files": ["data.h5ad"],
        "creation_date": "2026-01-15T12:00:00Z",
    },
    "deployment": {
        "cluster": "BN",
        "status": True,
        "auth": False,
        "bucket": "mampok-my-project-cellxgene",
        "lifetime": "2020-01-01T00:00:00Z",
        "url": "",
    },
    "service": {
        "analyst": ["jdoe"],
        "datatype": ["scRNA-seq"],
        "download_allowed": False,
        "metadata": [],
        "organization": ["bioinfo"],
        "owner": "jdoe",
        "user": ["jdoe"],
    },
}

MINIMAL_SHMAMPLAN = {
    "project": {
        "project_id": "jdoe-cellxgene",
        "tool": "cellxgene",
    },
    "deployment": {
        "cluster": "BN",
        "bucket": "mampok-jdoe-cellxgene",
        "lifetime": "2020-01-01T00:00:00Z",
        "status": True,
        "url": "",
    },
    "service": {
        "owner": "jdoe",
    },
}


class TestLoadMamplans:
    """load_mamplans() must find both Mamplan and SHMamplan files in a directory."""

    def test_directory_scan_finds_both_mamplan_and_shmamplan(self, tmp_path):
        (tmp_path / "my-project-mamplan.json").write_text(json.dumps(MINIMAL_MAMPLAN))
        (tmp_path / "jdoe-cellxgene-shmamplan.json").write_text(json.dumps(MINIMAL_SHMAMPLAN))

        loaded = load_mamplans(tmp_path)

        assert len(loaded) == 2
        by_id = {m.data["project"]["project_id"]: m for m in loaded}
        assert isinstance(by_id["my-project"], Mamplan)
        assert isinstance(by_id["jdoe-cellxgene"], SHMamplan)

    def test_expired_shmamplan_is_included_via_directory_scan(self, tmp_path):
        (tmp_path / "jdoe-cellxgene-shmamplan.json").write_text(json.dumps(MINIMAL_SHMAMPLAN))

        loaded = load_mamplans(tmp_path)

        assert len(loaded) == 1
        assert loaded[0].is_expired is True

    def test_warns_about_misnamed_mamplan_like_file(self, tmp_path, capsys):
        """A file that looks like a mamplan but has the wrong suffix is skipped with a warning."""
        (tmp_path / "my-project-mamplan.json").write_text(json.dumps(MINIMAL_MAMPLAN))
        (tmp_path / "igv_MaMPlan.json").write_text(json.dumps(MINIMAL_MAMPLAN))

        loaded = load_mamplans(tmp_path)

        assert len(loaded) == 1
        err = capsys.readouterr().err
        assert "igv_MaMPlan.json" in err
        assert "naming convention" in err

    def test_no_warning_for_unrelated_json_files(self, tmp_path, capsys):
        """Unrelated *.json files (e.g. pipeline outputs) must not trigger a warning."""
        (tmp_path / "my-project-mamplan.json").write_text(json.dumps(MINIMAL_MAMPLAN))
        (tmp_path / "multiqc_report.json").write_text("{}")

        loaded = load_mamplans(tmp_path)

        assert len(loaded) == 1
        assert capsys.readouterr().err == ""
