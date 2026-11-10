import ast
from pathlib import Path

import matplotlib.pyplot as plt

from he3sim.ui.theme import style_figure_for_ui


def test_theme_figure_styling() -> None:
    fig, ax = plt.subplots()
    style_figure_for_ui(fig, ax)
    assert ax.spines["top"].get_visible() is False
    assert ax.spines["right"].get_visible() is False
    plt.close(fig)


def test_all_ui_files_syntax() -> None:
    ui_dir = Path(__file__).parents[2] / "src/he3sim/ui"
    for py_file in ui_dir.rglob("*.py"):
        ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
