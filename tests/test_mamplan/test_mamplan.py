"""Tests für Mamplan, Mamplate und MamplanBase."""

import json
import copy
from pathlib import Path

import pytest
import jsonschema

from mampok.mamplan import Mamplan, Mamplate


# ---------------------------------------------------------------------------
# Fixtures
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
        "status": False,
        "auth": False,
        "bucket": "mampok-my-project-cellxgene",
        "lifetime": "2026-12-31T00:00:00Z",
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

MINIMAL_MAMPLATE = {
    "tool": "cellxgene",
    "image": "ghcr.io/chanzuckerberg/cellxgene:1.1.1",
    "containertype": "maincontainer",
    "ports": 5005,
    "resources": {
        "limits": {"cpu": "2", "memory": "4Gi"},
        "requests": {"cpu": "500m", "memory": "1Gi"},
    },
}


@pytest.fixture
def mamplan_data():
    return copy.deepcopy(MINIMAL_MAMPLAN)


@pytest.fixture
def mamplate_data():
    return copy.deepcopy(MINIMAL_MAMPLATE)


@pytest.fixture
def mamplan(mamplan_data):
    return Mamplan(mamplan_data)


@pytest.fixture
def mamplate(mamplate_data):
    return Mamplate(mamplate_data)


# ---------------------------------------------------------------------------
# TestMamplanBase
# ---------------------------------------------------------------------------

class TestMamplanBase:
    """Tests für MamplanBase-Mechanismen (via Mamplan/Mamplate)."""

    def test_valid_data_creates_instance(self, mamplan_data):
        mp = Mamplan(mamplan_data)
        assert mp.data == mamplan_data

    def test_invalid_data_raises_validation_error(self, mamplan_data):
        del mamplan_data["project"]["project_id"]
        with pytest.raises(jsonschema.ValidationError):
            Mamplan(mamplan_data)

    def test_wrong_type_raises_validation_error(self, mamplan_data):
        mamplan_data["deployment"]["status"] = "not-a-bool"
        with pytest.raises(jsonschema.ValidationError):
            Mamplan(mamplan_data)

    def test_pattern_violation_raises_validation_error(self, mamplan_data):
        mamplan_data["project"]["project_id"] = "My_Project"  # Großbuchstaben verboten
        with pytest.raises(jsonschema.ValidationError):
            Mamplan(mamplan_data)

    def test_schema_is_cached_per_class(self, mamplan_data, mamplate_data):
        mp1 = Mamplan(mamplan_data)
        mp2 = Mamplan(copy.deepcopy(mamplan_data))
        # Schema-Cache ist dasselbe Objekt (nicht nur gleich)
        assert mp1.schema is mp2.schema

    def test_mamplan_and_mamplate_have_separate_caches(self, mamplan_data, mamplate_data):
        mp = Mamplan(mamplan_data)
        mt = Mamplate(mamplate_data)
        # Verschiedene Schema-Dicts
        assert mp.schema is not mt.schema
        assert mp.schema["title"] == "Mamplan"
        assert mt.schema["title"] == "Mamplate"

    def test_schema_cached_in_class_not_instance(self, mamplan_data):
        Mamplan(mamplan_data)
        assert Mamplan._schema_cache is not None
        assert Mamplan._schema_cache["title"] == "Mamplan"


# ---------------------------------------------------------------------------
# TestMamplan
# ---------------------------------------------------------------------------

class TestMamplan:
    """Tests für die Mamplan-Klasse."""

    # --- __init__ ---

    def test_init_minimal(self, mamplan_data):
        mp = Mamplan(mamplan_data)
        assert mp.data["project"]["tool"] == "cellxgene"

    def test_init_with_optional_fields(self, mamplan_data):
        mamplan_data["tags"] = {"gse": "GSE12345"}
        mamplan_data["project"]["init_container"] = ["s3download"]
        mp = Mamplan(mamplan_data)
        assert mp.data["tags"]["gse"] == "GSE12345"

    def test_init_missing_required_field(self, mamplan_data):
        del mamplan_data["deployment"]["cluster"]
        with pytest.raises(jsonschema.ValidationError):
            Mamplan(mamplan_data)

    # --- check_schema ---

    def test_check_schema_returns_true(self, mamplan):
        assert mamplan.check_schema() is True

    # --- read_in ---

    def test_read_in_valid_file(self, mamplan_data, tmp_path):
        path = tmp_path / "test-mamplan.json"
        path.write_text(json.dumps(mamplan_data), encoding="utf-8")
        mp = Mamplan.read_in(path)
        assert mp.data == mamplan_data

    def test_read_in_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Mamplan.read_in(tmp_path / "nonexistent.json")

    def test_read_in_invalid_json_syntax(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            Mamplan.read_in(path)

    def test_read_in_schema_violation(self, mamplan_data, tmp_path):
        del mamplan_data["service"]
        path = tmp_path / "bad-mamplan.json"
        path.write_text(json.dumps(mamplan_data), encoding="utf-8")
        with pytest.raises(jsonschema.ValidationError):
            Mamplan.read_in(path)

    # --- write ---

    def test_write_and_read_roundtrip(self, mamplan, tmp_path):
        path = tmp_path / "output.json"
        mamplan.write(path)
        mp2 = Mamplan.read_in(path)
        assert mp2.data == mamplan.data

    def test_write_to_directory_uses_auto_filename(self, mamplan, tmp_path):
        mamplan.write(tmp_path)
        expected = tmp_path / "my-project-mamplan.json"
        assert expected.exists()
        mp2 = Mamplan.read_in(expected)
        assert mp2.data == mamplan.data

    def test_write_preserves_all_fields(self, mamplan_data, tmp_path):
        mamplan_data["tags"] = {"gse": "GSE999", "pubmedid": 12345678}
        mp = Mamplan(mamplan_data)
        path = tmp_path / "full.json"
        mp.write(path)
        mp2 = Mamplan.read_in(path)
        assert mp2.data["tags"] == mamplan_data["tags"]

    def test_write_indent_format(self, mamplan, tmp_path):
        path = tmp_path / "output.json"
        mamplan.write(path)
        content = path.read_text(encoding="utf-8")
        # indent=2 → Zeilen beginnen mit Spaces
        assert "  " in content

    # --- edit ---

    def test_edit_simple_field(self, mamplan):
        mamplan.edit(deployment__auth=True)
        assert mamplan.data["deployment"]["auth"] is True

    def test_edit_nested_field(self, mamplan):
        mamplan.edit(deployment__status=True)
        assert mamplan.data["deployment"]["status"] is True

    def test_edit_multiple_fields(self, mamplan):
        mamplan.edit(deployment__status=True, deployment__auth=True)
        assert mamplan.data["deployment"]["status"] is True
        assert mamplan.data["deployment"]["auth"] is True

    def test_edit_invalid_rolls_back(self, mamplan):
        original_status = mamplan.data["deployment"]["status"]
        with pytest.raises(jsonschema.ValidationError):
            mamplan.edit(deployment__status="invalid-type")
        # Rollback: Dict unverändert
        assert mamplan.data["deployment"]["status"] == original_status

    def test_edit_rollback_does_not_affect_other_fields(self, mamplan):
        original = copy.deepcopy(mamplan.data)
        with pytest.raises(jsonschema.ValidationError):
            mamplan.edit(deployment__status="invalid", deployment__auth="also-invalid")
        assert mamplan.data == original

    # --- create ---

    def test_create_minimal(self):
        mp = Mamplan.create(
            project={
                "project_id": "test-project",
                "tool": "cellxgene",
                "files": ["data.h5ad"],
                "creation_date": "2026-01-01T00:00:00Z",
            },
            deployment={
                "cluster": "BN",
                "bucket": "mampok-test",
                "lifetime": "2026-12-31T00:00:00Z",
                "url": "",
            },
            service={
                "analyst": ["user1"],
                "datatype": ["scRNA-seq"],
                "metadata": [],
                "organization": ["bioinfo"],
                "owner": "user1",
                "user": ["user1"],
            },
        )
        assert isinstance(mp, Mamplan)

    def test_create_normalizes_project_id_lowercase(self):
        mp = Mamplan.create(
            project={
                "project_id": "MyProject",
                "tool": "cellxgene",
                "files": [],
                "creation_date": "2026-01-01T00:00:00Z",
            },
            deployment={
                "cluster": "BN",
                "bucket": "mampok-myproject",
                "lifetime": "2026-12-31T00:00:00Z",
                "url": "",
            },
            service={
                "analyst": ["u"],
                "datatype": ["x"],
                "metadata": [],
                "organization": ["o"],
                "owner": "u",
                "user": ["u"],
            },
        )
        assert mp.data["project"]["project_id"] == "myproject"

    def test_create_normalizes_project_id_underscores(self):
        mp = Mamplan.create(
            project={
                "project_id": "my_project_id",
                "tool": "cellxgene",
                "files": [],
                "creation_date": "2026-01-01T00:00:00Z",
            },
            deployment={
                "cluster": "BN",
                "bucket": "mampok-my-project-id",
                "lifetime": "2026-12-31T00:00:00Z",
                "url": "",
            },
            service={
                "analyst": ["u"],
                "datatype": ["x"],
                "metadata": [],
                "organization": ["o"],
                "owner": "u",
                "user": ["u"],
            },
        )
        assert mp.data["project"]["project_id"] == "my-project-id"

    def test_create_fills_deployment_defaults(self):
        mp = Mamplan.create(
            project={
                "project_id": "p",
                "tool": "t",
                "files": [],
                "creation_date": "2026-01-01T00:00:00Z",
            },
            deployment={
                "cluster": "BN",
                "bucket": "b",
                "lifetime": "2026-12-31T00:00:00Z",
                "url": "",
            },
            service={
                "analyst": ["u"],
                "datatype": ["x"],
                "metadata": [],
                "organization": ["o"],
                "owner": "u",
                "user": ["u"],
            },
        )
        assert mp.data["deployment"]["status"] is False
        assert mp.data["deployment"]["auth"] is False

    def test_create_fills_service_defaults(self):
        mp = Mamplan.create(
            project={
                "project_id": "p",
                "tool": "t",
                "files": [],
                "creation_date": "2026-01-01T00:00:00Z",
            },
            deployment={
                "cluster": "BN",
                "bucket": "b",
                "lifetime": "2026-12-31T00:00:00Z",
                "url": "",
            },
            service={
                "analyst": ["u"],
                "datatype": ["x"],
                "metadata": [],
                "organization": ["o"],
                "owner": "u",
                "user": ["u"],
            },
        )
        assert mp.data["service"]["download_allowed"] is False

    def test_create_does_not_override_explicit_values(self):
        mp = Mamplan.create(
            project={
                "project_id": "p",
                "tool": "t",
                "files": [],
                "creation_date": "2026-01-01T00:00:00Z",
            },
            deployment={
                "cluster": "BN",
                "bucket": "b",
                "lifetime": "2026-12-31T00:00:00Z",
                "url": "",
                "status": True,   # explizit gesetzt
                "auth": True,     # explizit gesetzt
            },
            service={
                "analyst": ["u"],
                "datatype": ["x"],
                "metadata": [],
                "organization": ["o"],
                "owner": "u",
                "user": ["u"],
                "download_allowed": True,
            },
        )
        assert mp.data["deployment"]["status"] is True
        assert mp.data["deployment"]["auth"] is True
        assert mp.data["service"]["download_allowed"] is True

    def test_create_missing_required_fields_raises(self):
        with pytest.raises(jsonschema.ValidationError):
            Mamplan.create(
                project={"tool": "cellxgene"},  # project_id fehlt
                deployment={"cluster": "BN"},
                service={},
            )

    # --- merge_container_config ---

    def test_merge_uses_mamplate_as_base(self, mamplan, mamplan_data, mamplate):
        result = mamplan.merge_container_config(mamplate, mamplan_data)
        assert result["main"]["image"] == mamplate.data["image"]
        assert result["main"]["ports"] == mamplate.data["ports"]

    def test_merge_mamplan_overrides_mamplate_scalar(self, mamplan_data, mamplate_data):
        mamplan_data["container"] = {"main": {"image": "custom-image:latest"}}
        mp = Mamplan(mamplan_data)
        mt = Mamplate(mamplate_data)
        result = mp.merge_container_config(mt, mamplan_data)
        assert result["main"]["image"] == "custom-image:latest"

    def test_merge_deep_merges_resources_dict(self, mamplan_data, mamplate_data):
        mamplan_data["container"] = {
            "main": {"resources": {"limits": {"cpu": "8"}}}
        }
        mp = Mamplan(mamplan_data)
        mt = Mamplate(mamplate_data)
        result = mp.merge_container_config(mt, mamplan_data)
        # cpu überschrieben, memory aus Mamplate erhalten
        assert result["main"]["resources"]["limits"]["cpu"] == "8"
        assert result["main"]["resources"]["limits"]["memory"] == "4Gi"
        # requests aus Mamplate vollständig erhalten
        assert result["main"]["resources"]["requests"]["cpu"] == "500m"

    def test_merge_replaces_list_fields(self, mamplan_data, mamplate_data):
        mamplate_data["args"] = ["--default-arg"]
        mamplan_data["container"] = {"main": {"args": ["--my-file", "data.h5ad"]}}
        mp = Mamplan(mamplan_data)
        mt = Mamplate(mamplate_data)
        result = mp.merge_container_config(mt, mamplan_data)
        assert result["main"]["args"] == ["--my-file", "data.h5ad"]

    def test_merge_mamplate_list_when_no_mamplan_override(self, mamplan_data, mamplate_data):
        mamplate_data["args"] = ["--default"]
        mp = Mamplan(mamplan_data)
        mt = Mamplate(mamplate_data)
        result = mp.merge_container_config(mt, mamplan_data)
        assert result["main"]["args"] == ["--default"]

    def test_merge_no_init_container_by_default(self, mamplan, mamplan_data, mamplate):
        result = mamplan.merge_container_config(mamplate, mamplan_data)
        assert "init" not in result

    def test_merge_init_container_from_project_init_container(self, mamplan_data, mamplate_data):
        mamplan_data["project"]["init_container"] = ["s3download"]
        mp = Mamplan(mamplan_data)
        mt = Mamplate(mamplate_data)
        init_mamplate_data = {**mamplate_data, "tool": "s3download", "image": "s3download:1.0"}
        init_mt = Mamplate(init_mamplate_data)
        result = mp.merge_container_config(mt, mamplan_data, [init_mt])
        assert "init" in result
        assert isinstance(result["init"], list)
        assert result["init"][0]["image"] == "s3download:1.0"
        assert result["init"][0]["tool"] == "s3download"

    def test_merge_init_container_from_container_init(self, mamplan_data, mamplate_data):
        mamplan_data["container"] = {"init": {"image": "init-image:latest"}}
        mp = Mamplan(mamplan_data)
        mt = Mamplate(mamplate_data)
        result = mp.merge_container_config(mt, mamplan_data)
        assert "init" in result
        assert isinstance(result["init"], list)
        assert result["init"][0]["image"] == "init-image:latest"

    def test_merge_does_not_modify_originals(self, mamplan_data, mamplate_data):
        mamplan_data["container"] = {"main": {"image": "override:latest"}}
        mp = Mamplan(mamplan_data)
        mt = Mamplate(mamplate_data)
        original_mamplate_image = mt.data["image"]
        mp.merge_container_config(mt, mamplan_data)
        assert mt.data["image"] == original_mamplate_image
        assert mp.data["container"]["main"]["image"] == "override:latest"


# ---------------------------------------------------------------------------
# TestMamplate
# ---------------------------------------------------------------------------

class TestMamplate:
    """Tests für die Mamplate-Klasse."""

    # --- __init__ ---

    def test_init_minimal(self, mamplate_data):
        mt = Mamplate(mamplate_data)
        assert mt.data["tool"] == "cellxgene"

    def test_init_maincontainer_without_ports_raises(self, mamplate_data):
        del mamplate_data["ports"]
        with pytest.raises(jsonschema.ValidationError):
            Mamplate(mamplate_data)

    def test_init_initcontainer_without_ports_ok(self, mamplate_data):
        mamplate_data["containertype"] = "initcontainer"
        del mamplate_data["ports"]
        mt = Mamplate(mamplate_data)
        assert mt.data["containertype"] == "initcontainer"

    def test_init_missing_required_field(self, mamplate_data):
        del mamplate_data["image"]
        with pytest.raises(jsonschema.ValidationError):
            Mamplate(mamplate_data)

    # --- read_in ---

    def test_read_in_valid_file(self, mamplate_data, tmp_path):
        path = tmp_path / "cellxgene-mamplate.json"
        path.write_text(json.dumps(mamplate_data), encoding="utf-8")
        mt = Mamplate.read_in(path)
        assert mt.data == mamplate_data

    def test_read_in_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Mamplate.read_in(tmp_path / "missing.json")

    # --- write ---

    def test_write_roundtrip(self, mamplate, tmp_path):
        path = tmp_path / "out.json"
        mamplate.write(path)
        mt2 = Mamplate.read_in(path)
        assert mt2.data == mamplate.data

    def test_write_to_directory_auto_filename(self, mamplate, tmp_path):
        mamplate.write(tmp_path)
        expected = tmp_path / "cellxgene-mamplate.json"
        assert expected.exists()

    # --- create ---

    def test_create_with_required_fields(self, mamplate_data):
        mt = Mamplate.create(**mamplate_data)
        assert mt.data["tool"] == "cellxgene"
        assert mt.data["containertype"] == "maincontainer"

    def test_create_missing_required_raises(self, mamplate_data):
        del mamplate_data["image"]
        with pytest.raises(jsonschema.ValidationError):
            Mamplate.create(**mamplate_data)

    def test_create_maincontainer_without_ports_raises(self, mamplate_data):
        del mamplate_data["ports"]
        with pytest.raises(jsonschema.ValidationError):
            Mamplate.create(**mamplate_data)

    # --- edit ---

    def test_edit_field(self, mamplate):
        mamplate.edit(image="new-image:2.0")
        assert mamplate.data["image"] == "new-image:2.0"

    def test_edit_invalid_rolls_back(self, mamplate):
        original_image = mamplate.data["image"]
        with pytest.raises(jsonschema.ValidationError):
            mamplate.edit(containertype="invalid-type")
        assert mamplate.data["image"] == original_image
        assert mamplate.data["containertype"] == "maincontainer"


class TestMamplanIsExpired:
    """Tests für Mamplan.is_expired Property."""

    def test_expired_active_returns_true(self, mamplan_data):
        mamplan_data["deployment"]["status"] = True
        mamplan_data["deployment"]["lifetime"] = "2020-01-01T00:00:00+00:00"
        assert Mamplan(mamplan_data).is_expired is True

    def test_not_expired_active_returns_false(self, mamplan_data):
        mamplan_data["deployment"]["status"] = True
        mamplan_data["deployment"]["lifetime"] = "2099-12-31T00:00:00+00:00"
        assert Mamplan(mamplan_data).is_expired is False

    def test_inactive_never_expired(self, mamplan_data):
        mamplan_data["deployment"]["status"] = False
        mamplan_data["deployment"]["lifetime"] = "2020-01-01T00:00:00+00:00"
        assert Mamplan(mamplan_data).is_expired is False

    def test_timezone_naive_treated_as_utc(self, mamplan_data):
        mamplan_data["deployment"]["status"] = True
        mamplan_data["deployment"]["lifetime"] = "2020-01-01T00:00:00"
        assert Mamplan(mamplan_data).is_expired is True

    def test_timezone_aware_future_not_expired(self, mamplan_data):
        mamplan_data["deployment"]["status"] = True
        mamplan_data["deployment"]["lifetime"] = "2099-01-01T00:00:00+02:00"
        assert Mamplan(mamplan_data).is_expired is False


# ---------------------------------------------------------------------------
# TestTemplateSubstitution
# ---------------------------------------------------------------------------

class TestTemplateSubstitution:
    """Tests für __key.subkey__-Template-Substitution in merge_container_config."""

    def _make_mamplate_with_args(self, mamplate_data, args):
        data = copy.deepcopy(mamplate_data)
        data["args"] = args
        return Mamplate(data)

    def _make_mamplate_with_command(self, mamplate_data, command):
        data = copy.deepcopy(mamplate_data)
        data["command"] = command
        return Mamplate(data)

    def test_string_value_substituted_in_args(self, mamplan_data, mamplate_data):
        mt = self._make_mamplate_with_args(mamplate_data, ["--owner", "__service.owner__"])
        mp = Mamplan(mamplan_data)
        result = mp.merge_container_config(mt, mamplan_data)
        assert result["main"]["args"] == ["--owner", "jdoe"]

    def test_list_value_comma_separated(self, mamplan_data, mamplate_data):
        mamplan_data["project"]["files"] = ["a.h5ad", "b.h5ad"]
        mt = self._make_mamplate_with_args(mamplate_data, ["--files", "__project.files__"])
        mp = Mamplan(mamplan_data)
        result = mp.merge_container_config(mt, mamplan_data)
        assert result["main"]["args"] == ["--files", "a.h5ad,b.h5ad"]

    def test_list_with_single_element(self, mamplan_data, mamplate_data):
        mt = self._make_mamplate_with_args(mamplate_data, ["--file", "__project.files__"])
        mp = Mamplan(mamplan_data)
        result = mp.merge_container_config(mt, mamplan_data)
        assert result["main"]["args"] == ["--file", "data.h5ad"]

    def test_token_in_path_prefix(self, mamplan_data, mamplate_data):
        mt = self._make_mamplate_with_args(mamplate_data, ["/DOWNLOADS3/__project.files__"])
        mp = Mamplan(mamplan_data)
        result = mp.merge_container_config(mt, mamplan_data)
        assert result["main"]["args"] == ["/DOWNLOADS3/data.h5ad"]

    def test_substitution_in_command_field(self, mamplan_data, mamplate_data):
        mt = self._make_mamplate_with_command(mamplate_data, ["launch", "__project.files__"])
        mp = Mamplan(mamplan_data)
        result = mp.merge_container_config(mt, mamplan_data)
        assert result["main"]["command"] == ["launch", "data.h5ad"]

    def test_multiple_tokens_in_same_string(self, mamplan_data, mamplate_data):
        mt = self._make_mamplate_with_args(
            mamplate_data, ["__service.owner__:__project.files__"]
        )
        mp = Mamplan(mamplan_data)
        result = mp.merge_container_config(mt, mamplan_data)
        assert result["main"]["args"] == ["jdoe:data.h5ad"]

    def test_unknown_path_raises_value_error(self, mamplan_data, mamplate_data):
        mt = self._make_mamplate_with_args(mamplate_data, ["__nonexistent.key__"])
        mp = Mamplan(mamplan_data)
        with pytest.raises(ValueError, match="nonexistent.key"):
            mp.merge_container_config(mt, mamplan_data)

    def test_nested_path_via_tags(self, mamplan_data, mamplate_data):
        mamplan_data["tags"] = {"gse": "GSE123456"}
        mt = self._make_mamplate_with_args(mamplate_data, ["--gse", "__tags.gse__"])
        mp = Mamplan(mamplan_data)
        result = mp.merge_container_config(mt, mamplan_data)
        assert result["main"]["args"] == ["--gse", "GSE123456"]

    def test_bool_value_lowercase_string(self, mamplan_data, mamplate_data):
        mt = self._make_mamplate_with_args(mamplate_data, ["--auth", "__deployment.auth__"])
        mp = Mamplan(mamplan_data)
        result = mp.merge_container_config(mt, mamplan_data)
        assert result["main"]["args"] == ["--auth", "false"]

    def test_no_tokens_args_unchanged(self, mamplan_data, mamplate_data):
        mt = self._make_mamplate_with_args(mamplate_data, ["--plain", "value"])
        mp = Mamplan(mamplan_data)
        result = mp.merge_container_config(mt, mamplan_data)
        assert result["main"]["args"] == ["--plain", "value"]

    def test_substitution_does_not_mutate_mamplate(self, mamplan_data, mamplate_data):
        mamplate_data["args"] = ["__project.files__"]
        mt = Mamplate(mamplate_data)
        mp = Mamplan(mamplan_data)
        mp.merge_container_config(mt, mamplan_data)
        assert mt.data["args"] == ["__project.files__"]
