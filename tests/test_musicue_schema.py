import json
from pathlib import Path

import pytest

from cedartoy.musicue import (
    MusiCueBundle,
    SUPPORTED_SCHEMA_MAJOR,
    UnsupportedSchemaError,
    load_bundle,
)


def _payload(schema_version: str = "1.0") -> dict:
    return {
        "schema_version": schema_version,
        "source_sha256": "x" * 64,
        "duration_sec": 10.0,
        "fps": 24.0,
        "tempo": {"bpm_global": 120.0, "bpm_curve": [], "time_signature": [4, 4]},
        "beats": [],
        "sections": [],
        "drums": {},
        "midi": {},
        "midi_energy": {},
        "stems_energy": {},
        "global_energy": {"hop_sec": 0.04, "values": []},
        "cuesheet": {"schema_version": "1.2", "source_sha256": "x" * 64,
                     "grammar": "concert_visuals", "duration_sec": 10.0,
                     "fps": 24.0, "drop_frame": False, "tempo_map": [], "tracks": []},
    }


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return p


def test_loads_minimal_bundle(tmp_path):
    bundle = load_bundle(_write(tmp_path, "b.musicue.json", _payload()))
    assert isinstance(bundle, MusiCueBundle)
    assert bundle.schema_version == "1.0"
    assert bundle.duration_sec == 10.0


def test_rejects_unsupported_major(tmp_path):
    path = _write(tmp_path, "b.musicue.json", _payload("2.0"))
    with pytest.raises(UnsupportedSchemaError) as exc:
        load_bundle(path)
    assert "2.0" in str(exc.value)
    assert str(SUPPORTED_SCHEMA_MAJOR) in str(exc.value)


def test_accepts_higher_minor(tmp_path):
    bundle = load_bundle(_write(tmp_path, "b.musicue.json", _payload("1.7")))
    assert bundle.schema_version == "1.7"


def test_rejects_malformed_json(tmp_path):
    path = tmp_path / "b.musicue.json"
    path.write_text("not json")
    with pytest.raises(ValueError):
        load_bundle(path)
