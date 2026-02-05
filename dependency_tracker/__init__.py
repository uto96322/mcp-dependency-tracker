"""
Dependency Tracker - TypeScript/JavaScript 의존성 추적 및 Breaking Change 감지

모듈 구조:
- config: 전역 설정 및 상태 관리
- parser: AST 파싱 및 Import/Export 추출
- path_resolver: 경로 해석 및 tsconfig.json 매핑
- dependency_graph: 의존성 그래프 빌드 및 분석
- breaking_changes: Breaking Change 감지 및 Cascade Fix 제안
- field_tracker: 필드 정의 추출 및 사용처 추적
- rename_refactor: 심볼 이름 변경 (VSCode F2-style)
- cache: 의존성 그래프 캐시 관리
- server: MCP 서버 메인 진입점
"""

__version__ = "2.0.0"
__author__ = "StudyGPTor Team"

# 주요 함수 export
from .dependency_graph import build_dependency_graph, calculate_all_dependents
from .breaking_changes import detect_breaking_changes, suggest_cascade_fix
from .field_tracker import track_field_usage
from .rename_refactor import rename_symbol

__all__ = [
    "build_dependency_graph",
    "calculate_all_dependents",
    "detect_breaking_changes",
    "suggest_cascade_fix",
    "track_field_usage",
    "rename_symbol",
]
