#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Breaking Change 감지 및 Cascade Fix 제안

이 모듈은 export 변경 시 발생하는 Breaking Change를 감지하고,
영향받는 파일들에 대한 수정 제안을 생성합니다.
"""
import sys
from typing import Dict, List

from . import config
from .parser import get_used_imports


def detect_breaking_changes(file_path: str, old_exports: List[str], new_exports: List[str]) -> Dict:
    """
    파일의 export 변경 감지

    Returns:
        {
            "removed": ["oldFunction"],
            "added": ["newFunction"],
            "risk": "high",  # high, medium, low
            "affected_files": ["file1.ts", "file2.ts"]
        }
    """
    removed = set(old_exports) - set(new_exports)
    added = set(new_exports) - set(old_exports)

    # ⭐ Bug Fix: 제거된 export를 실제로 import하는 파일만 찾기
    affected_files = []
    if file_path in config.DEPENDENCY_GRAPH and removed:
        for dependent in config.DEPENDENCY_GRAPH[file_path]["dependents"]:
            if dependent in config.DEPENDENCY_GRAPH:
                named_imports = config.DEPENDENCY_GRAPH[dependent].get("named_imports", {})
                imports_from_file = named_imports.get(file_path, [])
                # 제거된 export 중 하나라도 import했는지 확인
                if any(removed_export in imports_from_file for removed_export in removed):
                    affected_files.append(dependent)

    # 위험도 평가
    if removed and len(affected_files) > 5:
        risk = "high"
    elif removed and len(affected_files) > 0:
        risk = "medium"
    else:
        risk = "low"

    return {
        "removed": list(removed),
        "added": list(added),
        "risk": risk,
        "affected_files": affected_files
    }


def suggest_cascade_fix(file_path: str, removed_exports: List[str]) -> Dict:
    """
    Breaking Change에 대한 Cascade Fix 제안 (Phase 1 개선: AST 추적)

    Returns:
        {
            "affected_files": [
                {
                    "file": "src/controllers/user.ts",
                    "imports_to_remove": ["getUserById"],
                    "suggestion": "Replace getUserById with getUser"
                }
            ],
            "false_positives": 2  # import했지만 실제로 사용 안 함
        }
    """
    suggestions = []
    false_positives = 0

    if file_path not in config.DEPENDENCY_GRAPH:
        return {"affected_files": [], "false_positives": 0}

    dependents = config.DEPENDENCY_GRAPH[file_path]["dependents"]

    for dependent_file in dependents:
        if dependent_file not in config.DEPENDENCY_GRAPH:
            continue

        # 해당 파일이 제거된 export를 import하는지 확인
        named_imports = config.DEPENDENCY_GRAPH[dependent_file].get("named_imports", {})
        imports_from_file = named_imports.get(file_path, [])

        # removed_exports 중 import된 것만 필터링
        imported_removed = [imp for imp in imports_from_file if imp in removed_exports]

        if not imported_removed:
            # 이 파일은 removed exports를 import하지 않음
            continue

        # ⭐ Phase 1 개선: 실제로 사용하는지 AST로 확인
        actually_used = get_used_imports(dependent_file, imported_removed)

        if actually_used:
            # 실제로 사용 중 → 수정 필요
            suggestions.append({
                "file": dependent_file,
                "imports_to_remove": actually_used,
                "all_imports": imports_from_file,
                "suggestion": f"Update imports: {', '.join(actually_used)} 실제 사용 중지 또는 대체"
            })
        else:
            # import했지만 실제로 사용 안 함 → False Positive
            false_positives += 1
            print(f"[DEBUG] False Positive: {dependent_file} imports {imported_removed} but doesn't use them", file=sys.stderr)

    return {
        "affected_files": suggestions,
        "false_positives": false_positives  # ⭐ False Positive 감지
    }
