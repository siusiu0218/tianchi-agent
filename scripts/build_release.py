"""Package an allowlisted source snapshot without credentials or competition data."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / n for n in ("app.py", "run.ps1", "requirements.txt", "requirements-lock.txt", "RELEASE_GUIDE.md")]
    paths.append(ROOT / ".streamlit" / "config.toml")
    paths += sorted((ROOT / "copilot").glob("*.py"))
    paths += sorted((ROOT / "tests").glob("*.py"))
    paths += sorted((ROOT / "scripts").glob("*.py"))
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    manifest = {"release": "v0.1", "python": platform.python_version(), "files": hashes,
                "data_included": False, "credentials_included": False,
                "data_sha256": hashlib.sha256((ROOT / "赛题 1：数据共情者-业务数据.xlsx").read_bytes()).hexdigest()}
    zip_path = args.output / "共情副驾-v0.1-源码.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for p in paths:
            archive.write(p, p.relative_to(ROOT).as_posix())
        archive.writestr("README.md", (ROOT / "RELEASE_GUIDE.md").read_text(encoding="utf-8"))
        archive.writestr("release-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.write(ROOT / "artifacts" / "evaluation.json", "evaluation.json")
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.testzip() is None
        assert not any(n.endswith((".xlsx", ".db", ".sqlite3")) or Path(n).name.startswith(".env") for n in archive.namelist())
        for name, expected in hashes.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected
    manifest["zip_sha256"] = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (args.output / "release-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "evaluation.json").write_bytes((ROOT / "artifacts" / "evaluation.json").read_bytes())
    (args.output / "运行与演示指南.md").write_bytes((ROOT / "RELEASE_GUIDE.md").read_bytes())
    print(json.dumps({"zip": str(zip_path), "files": len(paths), "sha256": manifest["zip_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
