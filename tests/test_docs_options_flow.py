from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_readme_links_to_options_flow() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "[Options flow diagram](docs/OPTIONS_FLOW.md)" in readme


def test_options_flow_labels_the_top_level_save_and_navigation_actions() -> None:
    doc_text = (PROJECT_ROOT / "docs" / "OPTIONS_FLOW.md").read_text(encoding="utf-8")
    intro, diagram, walkthrough = doc_text.split("```", maxsplit=2)
    instructions = " ".join((intro + walkthrough).split())

    labels = (
        "Save calibration",
        "Back to options",
        "Record anchors",
        "Change group",
        "Back to groups",
        "Undo last",
        "Save changes",
    )
    for label in labels:
        assert f"|{label}|" in diagram, f"Missing diagram action: {label}"
        assert f"**{label}**" in instructions, f"Missing instructions: {label}"

    save_paths = re.findall(r"(?m)^\s*(\w+)\s+-->(?:\|([^|\n]+)\|)?\s+saved\b", diagram)
    assert save_paths == [("optionsMenu", "Save changes")]
