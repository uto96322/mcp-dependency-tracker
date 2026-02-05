#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
전역 설정 및 상태 관리

이 모듈은 Dependency Tracker의 전역 변수와 Tree-sitter 언어 설정을 관리합니다.
모든 모듈이 이 설정을 공유하여 일관된 상태를 유지합니다.
"""
from typing import Dict, List, Any
from tree_sitter import Language

# Tree-sitter imports
try:
    import tree_sitter_python as tspython
    import tree_sitter_typescript as tstype
    import tree_sitter_javascript as tsjs
except ImportError:
    import sys
    print("[ERROR] tree-sitter not installed. Run: pip install tree-sitter tree-sitter-python tree-sitter-typescript tree-sitter-javascript", file=sys.stderr)
    sys.exit(1)

# ============================================================
# 전역 상태 변수
# ============================================================

# 의존성 그래프: {file_path: {"imports": [...], "exports": [...], "dependents": [...]}}
DEPENDENCY_GRAPH: Dict[str, Dict[str, Any]] = {}

# 프로젝트 루트 경로
PROJECT_ROOT: str = None

# tsconfig.json paths 매핑 캐시: {"@/lib": "/absolute/path/to/lib"}
PATH_MAPPINGS: Dict[str, str] = {}

# 성능 최적화: {file_path: {identifier: is_used}}
USAGE_CACHE: Dict[str, Dict[str, bool]] = {}

# ============================================================
# Tree-sitter 언어 설정
# ============================================================

# TypeScript 언어
TS_LANGUAGE = Language(tstype.language_typescript())

# TSX 언어 (React)
TSX_LANGUAGE = Language(tstype.language_tsx())

# JavaScript 언어
JS_LANGUAGE = Language(tsjs.language())

# Python 언어
PY_LANGUAGE = Language(tspython.language())

# ============================================================
# 유틸리티 함수
# ============================================================

def reset_state():
    """전역 상태 초기화 (테스트용)"""
    global DEPENDENCY_GRAPH, PROJECT_ROOT, PATH_MAPPINGS, USAGE_CACHE
    DEPENDENCY_GRAPH = {}
    PROJECT_ROOT = None
    PATH_MAPPINGS = {}
    USAGE_CACHE = {}

def get_state_info() -> Dict[str, Any]:
    """현재 상태 정보 반환 (디버깅용)"""
    return {
        "dependency_graph_size": len(DEPENDENCY_GRAPH),
        "project_root": PROJECT_ROOT,
        "path_mappings_count": len(PATH_MAPPINGS),
        "cache_size": len(USAGE_CACHE)
    }
