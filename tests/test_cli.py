from pathlib import Path

from app.main import cli


def test_cli_can_protect_multiple_exact_terms(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    output = tmp_path / "output.txt"
    source.write_text(
        "We would like to better understand Project Aurora. In order to proceed, reply.",
        encoding="utf-8",
    )

    exit_code = cli([
        str(source),
        "--output", str(output),
        "--protect", "We would like to better understand",
        "--protect", "Project Aurora",
    ])

    assert exit_code == 0
    assert output.read_text(encoding="utf-8") == (
        "We would like to better understand Project Aurora. To proceed, reply."
    )


def test_cli_reports_invalid_invisible_protected_term(tmp_path: Path, capsys) -> None:
    source = tmp_path / "input.txt"
    source.write_text("Project Aurora", encoding="utf-8")

    assert cli([str(source), "--protect", "Project\u200bAurora"]) == 2
    assert "unsichtbaren Steuer- oder Formatzeichen" in capsys.readouterr().err
