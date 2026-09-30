import hashlib
import importlib.util
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from jiffin.engine import llama_release

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "fetch_llama_cpp.py"


@pytest.fixture
def fetcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fetch_llama_cpp", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_a_download_is_kept_only_when_its_sha256_matches(
    tmp_path: Path, fetcher: ModuleType
) -> None:
    source = tmp_path / "llama.zip"
    source.write_bytes(b"archive")
    target = tmp_path / "downloads" / "llama.zip"
    with pytest.raises(ValueError, match="sha256 mismatch"):
        fetcher.fetch(source.as_uri(), target, sha256(b"another archive"))
    assert list(target.parent.iterdir()) == []
    assert fetcher.fetch(source.as_uri(), target, sha256(b"archive")) == target
    assert target.read_bytes() == b"archive"


def test_every_archive_is_unpacked_into_one_folder(
    tmp_path: Path, fetcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    releases = tmp_path / "releases"
    releases.mkdir()
    archives = {
        "llama.zip": {"llama.dll": b"llama", "ggml.dll": b"ggml"},
        "cudart.zip": {"cudart64_13.dll": b"cuda"},
    }
    package = []
    for name, members in archives.items():
        with zipfile.ZipFile(releases / name, "w") as bundle:
            for member, data in members.items():
                bundle.writestr(member, data)
        package.append((name, sha256((releases / name).read_bytes())))
    monkeypatch.setattr(llama_release, "BASE_URL", releases.as_uri())
    monkeypatch.setattr(llama_release, "PACKAGE", tuple(package))
    monkeypatch.setattr(llama_release, "RUNTIMES", tmp_path / "runtimes")
    directory = fetcher.install()
    assert directory == llama_release.install_dir()
    assert sorted(path.name for path in directory.iterdir()) == [
        "cudart64_13.dll",
        "ggml.dll",
        "llama.dll",
    ]
    (releases / "llama.zip").unlink()
    assert fetcher.install() == directory  # already installed: nothing is fetched
