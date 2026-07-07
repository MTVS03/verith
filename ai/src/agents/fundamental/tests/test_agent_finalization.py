from __future__ import annotations

from pathlib import Path

from src.agents.fundamental.core.decisions import record_decision
from src.agents.fundamental.core.failures import record_failure
from src.agents.fundamental.core.run_history import append_history, recent_stats
from src.agents.fundamental.evidence.path_selector import select_evidence_paths
from src.agents.fundamental.interpret.critic import CriticOutput
from src.agents.fundamental.interpret.planner import AnalysisPlan


def test_planner_and_critic_schema_do_not_expose_numeric_fields() -> None:
    # planner/critic이 숫자·점수·라벨을 생산하지 않는다는 절대 경계를 고정한다.
    planner_fields = set(AnalysisPlan.model_fields)
    critic_fields = set(CriticOutput.model_fields)

    assert "score" not in planner_fields
    assert "label" not in planner_fields
    assert "value" not in planner_fields
    assert "score" not in critic_fields
    assert "label" not in critic_fields
    assert "value" not in critic_fields


def test_path_selector_links_metric_to_accounts_and_filings() -> None:
    graph = {
        "nodes": [
            {"id": "filing:1", "type": "filing", "rcept_no": "1", "source_url": "https://dart.example/1"},
            {
                "id": "account:1:ifrs-full_Revenue:revenue",
                "type": "account",
                "account_id": "ifrs-full_Revenue",
                "account_nm": "매출액",
                "role": "revenue",
                "fiscal_year": "2025",
                "rcept_no": "1",
                "source_url": "https://dart.example/1",
            },
            {"id": "metric:revenue_growth", "type": "metric", "metric": "revenue_growth", "label": "매출 성장률"},
        ],
        "edges": [
            {"from": "filing:1", "to": "account:1:ifrs-full_Revenue:revenue", "relation": "contains_account"},
            {"from": "account:1:ifrs-full_Revenue:revenue", "to": "metric:revenue_growth", "relation": "calculates"},
        ],
    }

    paths = select_evidence_paths(graph, ["revenue_growth"])

    assert paths[0]["metric"] == "revenue_growth"
    assert paths[0]["accounts"][0]["account_nm"] == "매출액"
    assert paths[0]["filings"][0]["rcept_no"] == "1"


def test_decision_failure_and_run_history_contract(tmp_path: Path) -> None:
    # run_history는 whitelist 저장이므로 임의 secret이 파일에 남으면 안 된다.
    decisions = record_decision(None, stage="planner", decision="fallback_plan", reason="테스트")
    failures = record_failure(None, failure_type="critic_skipped", stage="critic", message="테스트", retryable=True)
    history_path = tmp_path / "history.jsonl"

    append_history(
        {
            "trace_id": "trace-1",
            "request_id": "req-1",
            "ticker": "003670",
            "corp_name": "포스코퓨처엠",
            "report_mode": "annual",
            "score": 50,
            "label": "moderate",
            "llm_provider": "template",
            "llm_model": "rule-based",
            "failures": failures,
            "secret": "must-not-persist",
        },
        history_path,
    )

    text = history_path.read_text(encoding="utf-8")
    assert decisions[0]["stage"] == "planner"
    assert "must-not-persist" not in text
    assert recent_stats(path=history_path)["failure_runs"] == 1
