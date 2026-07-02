import subprocess
from pathlib import Path


def test_merge_snapshots_adds_index_and_toc(tmp_path: Path) -> None:
    target_dir = tmp_path / "snapshots"
    target_dir.mkdir()

    (target_dir / "alpha.txt").write_text(
        "==== File: /tmp/alpha.txt ====\n\nalpha line 1\nalpha line 2\n",
        encoding="utf-8",
    )
    (target_dir / "beta.txt").write_text(
        "==== File: /tmp/beta.txt ====\n\nbeta line 1\n",
        encoding="utf-8",
    )

    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "merge_snapshots.sh"

    subprocess.run(["bash", str(script), str(target_dir), "1"], check=True, cwd=repo_root)

    merged = next(
        path for path in target_dir.glob("*.txt") if path.name not in {"alpha.txt", "beta.txt"}
    )
    assert merged.exists()

    content = merged.read_text(encoding="utf-8")
    assert "== Inhaltsverzeichnis" in content

    lines = content.splitlines()
    for expected_line_number, line in enumerate(lines, start=1):
        assert line.startswith(f"{expected_line_number:06d} | ")

    toc_targets = {}
    for line in lines:
        if " | /tmp/" not in line:
            continue
        _, entry = line.split(" | ", 1)
        target_line, path = entry.split(" | ", 1)
        toc_targets[path] = int(target_line)

    assert set(toc_targets) == {"/tmp/alpha.txt", "/tmp/beta.txt"}
    for path, target_line in toc_targets.items():
        assert lines[target_line - 1] == f"{target_line:06d} | ==== File: {path} ===="
