"""모델 레지스트리 — 모든 ORM 모델을 import 해 `Base.metadata` 를 채운다.

Alembic env.py / 메타데이터 기반 도구가 전체 테이블을 인식하도록, 새 모델을 추가하면
이 모듈에 import 를 함께 등록한다.
"""

from __future__ import annotations

from db.base import Base

# Common
from db.models.common.agent_report import AgentReport
from db.models.common.stock import Stock
from db.models.common.stock_alias import StockAlias
from db.models.common.stock_corp_code import StockCorpCode

# Fundamental
from db.models.fundamental.fundamental_report import FundamentalReport
from db.models.fundamental.report_evidence import ReportEvidence
from db.models.fundamental.report_filing_snippet import ReportFilingSnippet
from db.models.fundamental.report_insight import ReportInsight
from db.models.fundamental.report_interpretation import FundamentalReportInterpretation
from db.models.fundamental.report_ratio import ReportRatio
from db.models.fundamental.report_verification import FundamentalReportVerification

# Technical
from db.models.technical.report_chart import TechnicalReportChart
from db.models.technical.report_followup import TechnicalReportFollowup
from db.models.technical.report_interpretation import TechnicalReportInterpretation
from db.models.technical.report_risk_note import TechnicalReportRiskNote
from db.models.technical.report_signal import TechnicalReportSignal
from db.models.technical.report_verification import TechnicalReportVerification
from db.models.technical.technical_report import TechnicalReport

# News
from db.models.news.news import News
from db.models.news.news_report import NewsReport

# Flow
from db.models.flow.flow_report import FlowReport
from db.models.flow.report_interpretation import FlowReportInterpretation
from db.models.flow.report_verification import FlowReportVerification

# Industry (5번째 에이전트 placeholder)
from db.models.industry.industry_report import IndustryReport

__all__ = [
    "Base",
    "AgentReport",
    "Stock",
    "StockAlias",
    "StockCorpCode",
    "FundamentalReport",
    "ReportEvidence",
    "ReportFilingSnippet",
    "ReportInsight",
    "FundamentalReportInterpretation",
    "ReportRatio",
    "FundamentalReportVerification",
    "TechnicalReportChart",
    "TechnicalReportFollowup",
    "TechnicalReportInterpretation",
    "TechnicalReportRiskNote",
    "TechnicalReportSignal",
    "TechnicalReportVerification",
    "TechnicalReport",
    "News",
    "NewsReport",
    "FlowReport",
    "FlowReportInterpretation",
    "FlowReportVerification",
    "IndustryReport",
]
