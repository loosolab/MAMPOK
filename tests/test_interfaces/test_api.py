"""Tests für Python-API."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, call, patch, mock_open

import pytest

from mampok.interfaces.api import API
from mampok.mamplan.mamplan import Mamplan


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config_path(tmp_path):
    """Dummy config path (existiert nicht — wird via from_file gepatcht)."""
    return tmp_path / "config.json"


@pytest.fixture
def mamplan_path(tmp_path):
    """Temp-Verzeichnis mit einer Mamplan-Datei."""
    return tmp_path / "test-proj-mamplan.json"


@pytest.fixture
def mock_mamplan_data():
    """Minimales Mamplan-Dict für Tests."""
    return {
        "project": {
            "project_id": "test-proj",
            "tool": "cellxgene",
            "files": [],
            "creation_date": "2024-01-01",
        },
        "deployment": {
            "cluster": "BN",
            "lifetime": "2099-12-31T00:00:00+00:00",
            "bucket": "test-bucket",
            "url": "https://test-proj.example.com",
            "status": False,
            "auth": False,
        },
        "service": {
            "analyst": "alice",
            "datatype": "scRNA",
            "owner": "alice",
            "user": ["alice"],
            "metadata": {},
            "organization": ["groupA"],
        },
        "tags": {
            "user": ["alice"],
            "organization": ["groupA"],
        },
    }


@pytest.fixture
def mock_mampok():
    """Mock Mampok-Orchestrator-Instanz."""
    mampok = MagicMock()
    mampok.deploy.return_value = iter([
        {"stage": "init", "status": "done", "project_id": "test-proj"},
        {"stage": "done", "selfservice": {"url": "https://test.example.com", "project_id": "test-proj", "auth": False}},
    ])
    mampok.check_status.return_value = {
        "project_id": "test-proj",
        "expected_active": False,
        "actually_deployed": False,
        "healthy": True,
    }
    mampok.mamplate = MagicMock()
    mampok.s3 = MagicMock()
    mampok.s3.bucket = "test-bucket"
    return mampok


@pytest.fixture
def api(config_path):
    """API-Instanz."""
    return API(config_path)


@pytest.fixture
def patched_api(api, mock_mamplan_data, mock_mampok, tmp_path):
    """API mit gepatchten _load und create_mampok_instance."""
    mamplan = MagicMock()
    mamplan.data = mock_mamplan_data
    mamplan.data["project"]["project_id"] = "test-proj"

    with patch.object(api, "_load_config"), \
         patch.object(api, "_load_mamplan", return_value=mamplan), \
         patch.object(api, "_load_mamplates", return_value={"cellxgene": MagicMock()}), \
         patch("mampok.interfaces.api.create_mampok_instance", return_value=mock_mampok):
        yield api, mamplan, mock_mampok


# ---------------------------------------------------------------------------
# TestAPIInit
# ---------------------------------------------------------------------------


class TestAPIInit:
    """Tests für API.__init__."""

    def test_stores_config_path(self, tmp_path):
        path = tmp_path / "config.json"
        api = API(path)
        assert api.config_path == path

    def test_converts_string_to_path(self, tmp_path):
        path = str(tmp_path / "config.json")
        api = API(path)
        assert isinstance(api.config_path, Path)


# ---------------------------------------------------------------------------
# TestAPIDeploy
# ---------------------------------------------------------------------------


class TestAPIDeploy:
    """Tests für API.deploy()."""

    def test_returns_iterator(self, patched_api):
        api, mamplan, mampok = patched_api
        result = api.deploy(Path("/fake/mamplan.json"))
        assert hasattr(result, "__iter__")

    def test_yields_events_from_mampok(self, patched_api):
        api, mamplan, mampok = patched_api
        events = list(api.deploy(Path("/fake/mamplan.json")))
        assert len(events) >= 1
        assert any(e.get("stage") == "done" for e in events)

    def test_calls_mampok_deploy(self, patched_api):
        api, mamplan, mampok = patched_api
        list(api.deploy(Path("/fake/mamplan.json")))
        mampok.deploy.assert_called_once()

    def test_final_event_has_selfservice(self, patched_api):
        api, mamplan, mampok = patched_api
        events = list(api.deploy(Path("/fake/mamplan.json")))
        done = next(e for e in events if e.get("stage") == "done")
        assert "selfservice" in done


# ---------------------------------------------------------------------------
# TestAPIStop
# ---------------------------------------------------------------------------


class TestAPIStop:
    """Tests für API.stop()."""

    def test_calls_mampok_stop(self, patched_api):
        api, mamplan, mampok = patched_api
        api.stop(Path("/fake/mamplan.json"))
        mampok.stop.assert_called_once()

    def test_returns_none(self, patched_api):
        api, mamplan, mampok = patched_api
        result = api.stop(Path("/fake/mamplan.json"))
        assert result is None


# ---------------------------------------------------------------------------
# TestAPIRedeploy
# ---------------------------------------------------------------------------


class TestAPIRedeploy:
    """Tests für API.redeploy()."""

    def test_returns_iterator(self, patched_api):
        api, mamplan, mampok = patched_api
        result = api.redeploy(Path("/fake/mamplan.json"))
        assert hasattr(result, "__iter__")

    def test_calls_stop_then_deploy(self, patched_api):
        api, mamplan, mampok = patched_api
        list(api.redeploy(Path("/fake/mamplan.json")))
        mampok.stop.assert_called_once()
        mampok.deploy.assert_called_once()

    def test_yields_stop_event_before_deploy_events(self, patched_api):
        api, mamplan, mampok = patched_api
        events = list(api.redeploy(Path("/fake/mamplan.json")))
        stages = [e.get("stage") for e in events]
        assert "stop" in stages
        stop_idx = stages.index("stop")
        init_idx = stages.index("init") if "init" in stages else len(stages)
        assert stop_idx < init_idx


# ---------------------------------------------------------------------------
# TestAPIEditMamplan
# ---------------------------------------------------------------------------


class TestAPIEditMamplan:
    """Tests für API.edit_mamplan()."""

    def test_updates_field_and_writes(self, tmp_path, mock_mamplan_data):
        mamplan_file = tmp_path / "test-proj-mamplan.json"
        mamplan_file.write_text(json.dumps(mock_mamplan_data))

        api = API(tmp_path / "config.json")
        with patch("mampok.interfaces.api.Mamplan.read_in") as mock_read, \
             patch.object(Mamplan, "write") as mock_write:
            mock_mp = MagicMock()
            mock_read.return_value = mock_mp

            api.edit_mamplan(mamplan_file, deployment__lifetime="2025-06-01T00:00:00")

            mock_mp.edit.assert_called_once_with(deployment__lifetime="2025-06-01T00:00:00")
            mock_mp.write.assert_called_once_with(mamplan_file)


# ---------------------------------------------------------------------------
# TestAPIEditLifetime
# ---------------------------------------------------------------------------


class TestAPIEditLifetime:
    """Tests für API.edit_lifetime()."""

    def test_calls_edit_with_correct_key(self, tmp_path, mock_mamplan_data):
        mamplan_file = tmp_path / "test-proj-mamplan.json"
        api = API(tmp_path / "config.json")

        with patch("mampok.interfaces.api.Mamplan.read_in") as mock_read:
            mock_mp = MagicMock()
            mock_read.return_value = mock_mp

            api.edit_lifetime(mamplan_file, "2025-06-01T00:00:00")

            mock_mp.edit.assert_called_once_with(deployment__lifetime="2025-06-01T00:00:00")
            mock_mp.write.assert_called_once_with(mamplan_file)


# ---------------------------------------------------------------------------
# TestAPIEditSharing
# ---------------------------------------------------------------------------


class TestAPIEditSharing:
    """Tests für API.edit_sharing()."""

    def test_yields_saved_event(self, tmp_path, mock_mamplan_data, api):
        with patch("mampok.interfaces.api.Mamplan.read_in") as mock_read:
            mock_mp = MagicMock()
            mock_mp.data = mock_mamplan_data
            mock_read.return_value = mock_mp

            events = list(api.edit_sharing(
                tmp_path / "test.json",
                users=["bob"],
                organizations=["groupB"],
            ))

        saved = next(e for e in events if e.get("stage") == "edit_sharing")
        assert saved["status"] == "saved"
        assert saved["project_id"] == "test-proj"

    def test_no_auth_secret_update_when_auth_false(self, tmp_path, mock_mamplan_data, api):
        mock_mamplan_data["deployment"]["auth"] = False
        mock_mamplan_data["deployment"]["status"] = True

        with patch("mampok.interfaces.api.Mamplan.read_in") as mock_read:
            mock_mp = MagicMock()
            mock_mp.data = mock_mamplan_data
            mock_read.return_value = mock_mp

            events = list(api.edit_sharing(tmp_path / "test.json", users=["bob"]))

        assert not any(e.get("stage") == "auth_secret" for e in events)

    def test_no_auth_secret_update_when_status_false(self, tmp_path, mock_mamplan_data, api):
        mock_mamplan_data["deployment"]["auth"] = True
        mock_mamplan_data["deployment"]["status"] = False

        with patch("mampok.interfaces.api.Mamplan.read_in") as mock_read:
            mock_mp = MagicMock()
            mock_mp.data = mock_mamplan_data
            mock_read.return_value = mock_mp

            events = list(api.edit_sharing(tmp_path / "test.json", users=["bob"]))

        assert not any(e.get("stage") == "auth_secret" for e in events)

    def test_auth_secret_updated_when_auth_and_status_true(
        self, tmp_path, mock_mamplan_data, api, mock_mampok
    ):
        mock_mamplan_data["deployment"]["auth"] = True
        mock_mamplan_data["deployment"]["status"] = True

        with patch("mampok.interfaces.api.Mamplan.read_in") as mock_read, \
             patch.object(api, "_load_config"), \
             patch.object(api, "_load_mamplates", return_value={}), \
             patch("mampok.interfaces.api.create_mampok_instance", return_value=mock_mampok):
            mock_mp = MagicMock()
            mock_mp.data = mock_mamplan_data
            mock_read.return_value = mock_mp

            events = list(api.edit_sharing(
                tmp_path / "test.json",
                users=["bob"],
                organizations=["groupB"],
            ))

        auth_event = next(e for e in events if e.get("stage") == "auth_secret")
        assert auth_event["status"] == "updated"
        mock_mampok.update_auth_secret.assert_called_once()

    def test_rollback_on_auth_secret_failure(
        self, tmp_path, mock_mamplan_data, api, mock_mampok
    ):
        """Mamplan wird zurückgesetzt wenn auth secret update fehlschlägt."""
        mock_mamplan_data["deployment"]["auth"] = True
        mock_mamplan_data["deployment"]["status"] = True
        mock_mampok.update_auth_secret.side_effect = RuntimeError("K8s unreachable")

        events = []
        with patch("mampok.interfaces.api.Mamplan.read_in") as mock_read, \
             patch.object(api, "_load_config"), \
             patch.object(api, "_load_mamplates", return_value={}), \
             patch("mampok.interfaces.api.create_mampok_instance", return_value=mock_mampok):
            mock_mp = MagicMock()
            mock_mp.data = mock_mamplan_data
            mock_read.return_value = mock_mp

            with pytest.raises(RuntimeError, match="K8s unreachable"):
                for event in api.edit_sharing(tmp_path / "test.json", users=["bob"]):
                    events.append(event)

        stages = [e["stage"] for e in events]
        assert "auth_secret" in stages
        assert "rollback" in stages
        # Rollback: write wurde nach dem Fehler aufgerufen
        assert mock_mp.write.call_count >= 2  # einmal für save, einmal für rollback


# ---------------------------------------------------------------------------
# TestAPIProjectInfo
# ---------------------------------------------------------------------------


class TestAPIProjectInfo:
    """Tests für API.project_info()."""

    def test_returns_projects_dict(self, patched_api, tmp_path):
        api, mamplan, mampok = patched_api
        mamplan_file = tmp_path / "test-proj-mamplan.json"
        mamplan_file.touch()
        result = api.project_info(mamplan_file)
        assert "projects" in result

    def test_single_mamplan_in_result(self, patched_api, tmp_path):
        api, mamplan, mampok = patched_api
        mamplan_file = tmp_path / "test-proj-mamplan.json"
        mamplan_file.touch()
        result = api.project_info(mamplan_file)
        assert "test-proj" in result["projects"]

    def test_includes_flat_project_fields(self, patched_api, tmp_path):
        api, mamplan, mampok = patched_api
        mamplan_file = tmp_path / "test-proj-mamplan.json"
        mamplan_file.touch()
        result = api.project_info(mamplan_file)
        proj = result["projects"]["test-proj"]
        assert "mamplan" not in proj
        assert proj["bucket"] == "test-bucket"
        assert proj["owner"] == "alice"
        assert proj["lifetime"] == "2099-12-31T00:00:00+00:00"

    def test_includes_status_from_kube(self, patched_api, tmp_path):
        api, mamplan, mampok = patched_api
        mamplan_file = tmp_path / "test-proj-mamplan.json"
        mamplan_file.touch()
        mampok.check_status.return_value["actually_deployed"] = True
        result = api.project_info(mamplan_file)
        assert result["projects"]["test-proj"]["status"] is True

    def test_writes_output_file_when_provided(self, patched_api, tmp_path):
        api, mamplan, mampok = patched_api
        mamplan_file = tmp_path / "test-proj-mamplan.json"
        mamplan_file.touch()
        output = tmp_path / "info.json"
        api.project_info(mamplan_file, output=output)
        assert output.exists()
        data = json.loads(output.read_text())
        assert "projects" in data

    def test_no_output_file_by_default(self, patched_api, tmp_path):
        api, mamplan, mampok = patched_api
        mamplan_file = tmp_path / "test-proj-mamplan.json"
        mamplan_file.touch()
        output = tmp_path / "info.json"
        api.project_info(mamplan_file)
        assert not output.exists()


# ---------------------------------------------------------------------------
# TestAPICreateMamplan
# ---------------------------------------------------------------------------


class TestAPICreateMamplan:
    """Tests für API.create_mamplan()."""

    def test_creates_and_writes_mamplan(self, tmp_path):
        api = API(tmp_path / "config.json")
        output = tmp_path / "new-mamplan.json"

        mock_config = MagicMock()
        mock_config.clusters = {"BN": MagicMock()}
        with patch("mampok.interfaces.api.Mamplan.create") as mock_create, \
             patch.object(api, "_load_config", return_value=mock_config), \
             patch.object(api, "_load_mamplates", return_value={"cellxgene": MagicMock()}):
            mock_mp = MagicMock()
            mock_create.return_value = mock_mp

            api.create_mamplan(output, project={"project_id": "new"})

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["project"] == {"project_id": "new"}
            # deployment.lifetime is auto-populated as ISO 8601 placeholder
            assert "lifetime" in call_kwargs.get("deployment", {})
            mock_mp.write.assert_called_once_with(output)


# ---------------------------------------------------------------------------
# TestAPIListExpiring
# ---------------------------------------------------------------------------


class TestAPIListExpiring:
    """Tests für API.list_expiring()."""

    def _make_mamplan(self, status: bool, lifetime: str, project_id: str = "proj") -> MagicMock:
        mp = MagicMock()
        mp.data = {
            "project": {"project_id": project_id},
            "deployment": {"status": status, "lifetime": lifetime},
        }
        return mp

    def test_returns_active_expiring_soon(self, api, tmp_path):
        future_7d = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        mamplan = self._make_mamplan(True, future_7d, "proj-a")
        with patch("mampok.interfaces.cli.load_mamplans", return_value=[mamplan]):
            result = api.list_expiring(tmp_path, within_days=7)
        assert len(result) == 1
        assert result[0]["project_id"] == "proj-a"

    def test_excludes_inactive_mamplan(self, api, tmp_path):
        future_3d = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        mamplan = self._make_mamplan(False, future_3d, "proj-b")
        with patch("mampok.interfaces.cli.load_mamplans", return_value=[mamplan]):
            result = api.list_expiring(tmp_path, within_days=7)
        assert result == []

    def test_excludes_already_expired(self, api, tmp_path):
        past = "2020-01-01T00:00:00+00:00"
        mamplan = self._make_mamplan(True, past, "proj-c")
        with patch("mampok.interfaces.cli.load_mamplans", return_value=[mamplan]):
            result = api.list_expiring(tmp_path, within_days=7)
        assert result == []

    def test_excludes_beyond_window(self, api, tmp_path):
        future_30d = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        mamplan = self._make_mamplan(True, future_30d, "proj-d")
        with patch("mampok.interfaces.cli.load_mamplans", return_value=[mamplan]):
            result = api.list_expiring(tmp_path, within_days=7)
        assert result == []

    def test_empty_repo_returns_empty_list(self, api, tmp_path):
        with patch("mampok.interfaces.cli.load_mamplans", return_value=[]):
            result = api.list_expiring(tmp_path)
        assert result == []
