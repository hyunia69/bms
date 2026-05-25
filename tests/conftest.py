"""pytest 부트스트랩 — scripts/ 를 sys.path 에 올린다.

scripts 는 패키지(__init__.py)가 아니라 직접 실행 스크립트 묶음이라
(answer_eval.py 의 `import rag_answer` 패턴), 테스트도 같은 경로 규약을 쓴다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
