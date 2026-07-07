from src.agents.fundamental.core.contract import Evidence
from src.agents.fundamental.verify.binding import check_evidence_binding


def evidence(**overrides) -> Evidence:
    data = {
        "claim": "ROE 3.0",
        "metric": "roe",
        "value": 3.0,
        "unit": "%",
        "fiscal_year": "2025",
        "rcept_no": "20260301000001",
        "account_ids": ["ifrs-full_ProfitLoss"],
        "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260301000001",
    }
    data.update(overrides)
    return Evidence(**data)


def test_check_evidence_binding_keeps_bound_items():
    bound, flags = check_evidence_binding([evidence()])

    assert len(bound) == 1
    assert flags == []


def test_check_evidence_binding_excludes_unbound_items():
    bound, flags = check_evidence_binding([evidence(account_ids=[])])

    assert bound == []
    assert flags == ["EVIDENCE_UNBOUND_EXCLUDED"]
