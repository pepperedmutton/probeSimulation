from pathlib import Path

from app.iv_simulation import report_cases


def test_report_cases_generates_file(tmp_path: Path, monkeypatch) -> None:
    # Redirect output path to tmpdir for isolated testing.
    monkeypatch.chdir(tmp_path)

    report_cases.main()

    report = tmp_path / "iv_results.txt"
    assert report.exists(), "report file missing"
    content = report.read_text()
    assert "Scenario" in content
    assert "Status" in content
    assert "Issues" not in content, "Unexpected issues found in baseline scenarios"
