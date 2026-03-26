"""Tests für mampok.mamplan.metadata."""

from pathlib import Path

import pytest
import yaml

from mampok.mamplan.metadata import _merge_unique, parse_metadata_files


# ---------------------------------------------------------------------------
# Fixtures: YAML-Inhalte
# ---------------------------------------------------------------------------

_YAML_SCH79 = {
    "project": {
        "id": "sch79",
        "project_name": "GLORI2 TEST",
        "owner": {"name": "Su, Jianbang", "ldap_name": "jsu", "department": "AG-aschnei"},
        "nerd": {"ldap_name": "bioinf_user"},
    },
    "technical_details": {
        "techniques": [
            {"setting": "exp1", "technique": ["GLORI-seq"]},
        ]
    },
}

_YAML_DST302 = {
    "project": {
        "id": "dst302",
        "project_name": "ATAC seq",
        "owner": {"name": "Gehlot, Rupal", "ldap_name": "rgehlot", "department": "Abt-K"},
        "nerd": {"ldap_name": "another_nerd"},
    },
    "technical_details": {
        "techniques": [
            {"setting": "exp1", "technique": ["bulk ATAC-seq"]},
            {"setting": "exp2", "technique": ["bulk ATAC-seq"]},
        ]
    },
}

_YAML_NO_NERD = {
    "project": {
        "id": "proj_no_nerd",
        "owner": {"ldap_name": "owner_user", "department": "AG-test"},
    },
    "technical_details": {
        "techniques": [{"technique": ["scRNA-seq"]}],
    },
}


@pytest.fixture
def yaml_sch79(tmp_path: Path) -> Path:
    path = tmp_path / "sch79_metadata.yaml"
    path.write_text(yaml.dump(_YAML_SCH79), encoding="utf-8")
    return path


@pytest.fixture
def yaml_dst302(tmp_path: Path) -> Path:
    path = tmp_path / "dst302_metadata.yaml"
    path.write_text(yaml.dump(_YAML_DST302), encoding="utf-8")
    return path


@pytest.fixture
def yaml_no_nerd(tmp_path: Path) -> Path:
    path = tmp_path / "no_nerd_metadata.yaml"
    path.write_text(yaml.dump(_YAML_NO_NERD), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests: parse_metadata_files
# ---------------------------------------------------------------------------

class TestParseMetadataFiles:
    def test_single_file(self, yaml_sch79: Path) -> None:
        result = parse_metadata_files([yaml_sch79])

        assert result["owner"] == "jsu"
        assert result["analyst"] == ["bioinf_user"]
        assert result["organization"] == ["AG-aschnei"]
        assert result["datatype"] == ["GLORI-seq"]
        assert result["metadata"] == ["sch79"]

    def test_multiple_files_lists_merged(self, yaml_sch79: Path, yaml_dst302: Path) -> None:
        result = parse_metadata_files([yaml_sch79, yaml_dst302])

        # owner: erstes File
        assert result["owner"] == "jsu"
        # Listen: beide gemergt
        assert result["analyst"] == ["bioinf_user", "another_nerd"]
        assert result["organization"] == ["AG-aschnei", "Abt-K"]
        assert result["datatype"] == ["GLORI-seq", "bulk ATAC-seq"]
        assert result["metadata"] == ["sch79", "dst302"]

    def test_datatype_deduplicated(self, yaml_dst302: Path) -> None:
        # dst302 hat bulk ATAC-seq in exp1 und exp2 – darf nur einmal erscheinen
        result = parse_metadata_files([yaml_dst302])
        assert result["datatype"].count("bulk ATAC-seq") == 1

    def test_no_nerd_analyst_empty(self, yaml_no_nerd: Path) -> None:
        result = parse_metadata_files([yaml_no_nerd])
        assert result["analyst"] == []
        assert result["owner"] == "owner_user"

    def test_empty_list(self) -> None:
        result = parse_metadata_files([])
        assert result == {"owner": "", "analyst": [], "organization": [], "datatype": [], "metadata": []}


# ---------------------------------------------------------------------------
# Tests: _merge_unique
# ---------------------------------------------------------------------------

class TestMergeUnique:
    def test_no_duplicates(self) -> None:
        assert _merge_unique(["a", "b"], ["c"]) == ["a", "b", "c"]

    def test_duplicate_skipped(self) -> None:
        assert _merge_unique(["a", "b"], ["b", "c"]) == ["a", "b", "c"]

    def test_empty_base(self) -> None:
        assert _merge_unique([], ["x", "y"]) == ["x", "y"]

    def test_empty_additions(self) -> None:
        assert _merge_unique(["x"], []) == ["x"]

    def test_order_preserved(self) -> None:
        assert _merge_unique(["z", "a"], ["b", "a", "c"]) == ["z", "a", "b", "c"]
