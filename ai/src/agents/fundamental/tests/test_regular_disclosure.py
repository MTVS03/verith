from src.agents.fundamental.data.regular_disclosure import _major_holder_insight


def test_major_holder_insight_excludes_total_rows():
    rows = [
        {
            "nm": "계",
            "relate": "-",
            "trmend_posesn_stock_co": "10,000",
            "trmend_posesn_stock_qota_rt": "60.60",
            "rcept_no": "20260301000001",
        },
        {
            "nm": "진짜최대주주",
            "relate": "본인",
            "trmend_posesn_stock_co": "4,000",
            "trmend_posesn_stock_qota_rt": "24.20",
            "rcept_no": "20260301000001",
        },
        {
            "nm": "특수관계인",
            "relate": "계열회사",
            "trmend_posesn_stock_co": "1,000",
            "trmend_posesn_stock_qota_rt": "6.10",
            "rcept_no": "20260301000001",
        },
    ]

    insight = _major_holder_insight(rows)

    assert insight["name"] == "진짜최대주주"
    assert insight["ratio"] == 24.2
