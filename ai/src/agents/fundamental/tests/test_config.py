from __future__ import annotations

from src.agents.fundamental.core.config import AI_ROOT


def test_ai_root_points_to_project_ai_directory() -> None:
    assert AI_ROOT.name == "ai"
    assert (AI_ROOT / "pyproject.toml").exists()
