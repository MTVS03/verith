# conftest.py
"""테스트 임포트 루트 설정.

news 에이전트 코드는 `from schemas.article import ...`, `import services.rss` 처럼
이 디렉터리를 임포트 루트로 삼는 절대 임포트를 쓴다(TASK 01 스키마와 동일 규약).
pytest가 이 conftest의 디렉터리를 sys.path에 넣도록 news 루트에 둔다.
"""
import os
import sys

_ROOT = os.path.dirname(__file__)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
