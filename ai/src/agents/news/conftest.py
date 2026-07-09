# conftest.py
"""테스트 임포트 루트 설정.

news 에이전트 코드는 저장소 표준대로 `from src.agents.news.schemas.article import ...`,
`import src.agents.news.services.rss as ...` 처럼 **패키지 경로**를 쓴다(다른 에이전트와 동일).
이 경로는 pytest `pythonpath = ["."]`(pyproject) 가 ai/ 를 sys.path 에 넣어 풀리므로, 여기서
news 디렉터리를 별도로 주입하지 않는다 — 주입하면 같은 모듈이 두 경로로 로드되는(=서로 다른
객체) 위험이 생긴다. 파일은 pytest 훅 확장 여지를 위해 남겨둔다.
"""
