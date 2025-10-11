from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_readme_links_to_options_flow() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "[Options flow diagram](docs/OPTIONS_FLOW.md)" in readme


def test_options_flow_contains_required_labels() -> None:
    doc_text = (PROJECT_ROOT / "docs" / "OPTIONS_FLOW.md").read_text(encoding="utf-8")
    required_phrases = [
        "Save",
        "Done/Record",
        "Cancel/Back",
        "No anchors saved",
        "largest-gap",
        "skip unchanged",
    ]
    for phrase in required_phrases:
        assert phrase in doc_text, f"Missing required phrase: {phrase!r}"
