#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
경로 해석 및 tsconfig.json 매핑

이 모듈은 TypeScript/JavaScript의 복잡한 경로 해석을 처리합니다:
- tsconfig.json의 paths 매핑
- 상대 경로 → 절대 경로 변환
- 확장자 추론
- index 파일 처리
"""
import os
import sys
import json
from pathlib import Path
from typing import Dict

from . import config


def load_tsconfig_paths(project_root: str) -> Dict[str, str]:
    """
    tsconfig.json paths 로드 (Phase 2 개선)
    - JSON5 주석 제거
    - baseUrl 고려
    - 디버그 로그 추가

    Returns:
        {"@": "./src", "@components": "./src/components", ...}
    """
    
    tsconfig_path = Path(project_root) / "tsconfig.json"

    if not tsconfig_path.exists():
        print(f"[DEBUG] tsconfig.json not found at {tsconfig_path}", file=sys.stderr)
        return {}

    try:
        with open(tsconfig_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 먼저 원본 JSON 파싱 시도
        try:
            tsconfig = json.loads(content)
        except json.JSONDecodeError:
            # JSON5 주석이 있는 경우에만 주석 제거 시도
            print(f"[DEBUG] JSON5 주석 제거 시도...", file=sys.stderr)

            lines = content.split('\n')
            cleaned_lines = []
            in_multiline_comment = False

            for line in lines:
                original_line = line

                # /* */ 여러 줄 주석 처리 (문자열 밖에 있을 때만)
                # 간단한 휴리스틱: 문자열 안의 /* */ 는 무시
                if not '"' in line or line.strip().startswith('//'):
                    if '/*' in line and not in_multiline_comment:
                        in_multiline_comment = True
                    if in_multiline_comment:
                        if '*/' in line:
                            in_multiline_comment = False
                            line = line.split('*/', 1)[-1] if '*/' in line else ''
                        else:
                            continue

                # // 한 줄 주석 제거 (문자열 밖에 있는 경우만)
                if '//' in line:
                    # 문자열 내부가 아닌 경우만 제거
                    parts = line.split('"')
                    # 짝수 인덱스는 문자열 밖
                    for i in range(0, len(parts), 2):
                        if '//' in parts[i]:
                            parts[i] = parts[i].split('//')[0]
                    line = '"'.join(parts)

                cleaned_lines.append(line)

            content = '\n'.join(cleaned_lines)
            tsconfig = json.loads(content)

        compiler_options = tsconfig.get('compilerOptions', {})
        base_url = compiler_options.get('baseUrl', '.')
        paths = compiler_options.get('paths', {})

        print(f"[DEBUG] baseUrl: {base_url}", file=sys.stderr)
        print(f"[DEBUG] paths: {paths}", file=sys.stderr)

        mappings = {}

        for alias, targets in paths.items():
            if not targets or not isinstance(targets, list):
                continue

            target = targets[0]

            # Wildcard 처리
            if alias.endswith('/*'):
                alias_base = alias[:-2]  # "@components/*" → "@components"
                target_base = target[:-2] if target.endswith('/*') else target
            else:
                alias_base = alias
                target_base = target

            # baseUrl 고려
            if not target_base.startswith('.'):
                target_base = f"./{target_base}"

            mappings[alias_base] = target_base
            print(f"[DEBUG] Mapped: {alias_base} → {target_base}", file=sys.stderr)

        return mappings

    except Exception as e:
        print(f"[ERROR] Failed to load tsconfig.json: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {}


def resolve_import_path(import_path: str, current_file: str, project_root: str) -> str:
    """
    상대 경로를 절대 경로로 변환 (Phase 2 개선)

    Examples:
        ./user → /project/src/services/user.ts
        @/lib/db → /project/src/lib/db.ts
        @components → /project/src/components/index.ts
        utils (Python) → /project/utils.py
    """
    current_dir = os.path.dirname(current_file)

    # 0. Python 현재 디렉토리 import (from utils import ...)
    # Python은 확장자 없는 모듈 이름으로 import
    if current_file.endswith('.py') and not import_path.startswith('.') and not import_path.startswith('@'):
        # 현재 디렉토리에서 찾기
        resolved = os.path.join(current_dir, import_path)
        print(f"[DEBUG] Python module: {import_path} → {resolved}", file=sys.stderr)

    # 1. 상대 경로 (./, ../)
    elif import_path.startswith('.'):
        resolved = os.path.normpath(os.path.join(current_dir, import_path))
        print(f"[DEBUG] Relative: {import_path} → {resolved}", file=sys.stderr)

    # 2. tsconfig paths 매핑 확인
    elif config.PATH_MAPPINGS:
        resolved = None

        # ⭐ Phase 2 개선: 가장 긴 매칭부터 시도 (더 구체적인 alias 우선)
        sorted_aliases = sorted(config.PATH_MAPPINGS.keys(), key=len, reverse=True)

        for alias in sorted_aliases:
            target = config.PATH_MAPPINGS[alias]

            # 정확히 일치하는 경우
            if import_path == alias:
                resolved = os.path.join(project_root, target.lstrip('./'))
                print(f"[DEBUG] Exact match: {import_path} → {resolved}", file=sys.stderr)
                break

            # Prefix 매칭 (예: @components/Button)
            if import_path.startswith(alias + '/'):
                remainder = import_path[len(alias) + 1:]  # "Button"
                target_base = os.path.join(project_root, target.lstrip('./'))
                resolved = os.path.join(target_base, remainder)
                print(f"[DEBUG] Prefix match: {import_path} → {resolved}", file=sys.stderr)
                break

        if not resolved:
            # ⭐ Bug Fix: @/ → 프로젝트 루트 (기존: src/)
            if import_path.startswith('@/'):
                resolved = os.path.join(project_root, import_path[2:])
                print(f"[DEBUG] Fallback @/: {import_path} → {resolved}", file=sys.stderr)
            else:
                print(f"[WARN] No alias match for: {import_path}", file=sys.stderr)
                return None
    else:
        # ⭐ Bug Fix: PATH_MAPPINGS가 없으면 @/ → 프로젝트 루트
        if import_path.startswith('@/'):
            resolved = os.path.join(project_root, import_path[2:])
        else:
            # node_modules (무시)
            return None

    # 3. 확장자 추론
    if resolved:
        # ⭐ Bug Fix: 경로 정규화 (슬래시/백슬래시 혼합 방지)
        resolved = os.path.normpath(resolved)

        for ext in ['.ts', '.tsx', '.js', '.jsx', '.py']:
            if os.path.exists(resolved + ext):
                resolved = resolved + ext
                print(f"[DEBUG] Found with ext: {resolved}", file=sys.stderr)
                return resolved

        # 4. index/__init__ 파일 확인
        for ext in ['.ts', '.tsx', '.js', '.jsx']:
            index_path = os.path.join(resolved, f'index{ext}')
            if os.path.exists(index_path):
                resolved = index_path
                print(f"[DEBUG] Found index: {resolved}", file=sys.stderr)
                return resolved

        # Python __init__.py
        init_path = os.path.join(resolved, '__init__.py')
        if os.path.exists(init_path):
            resolved = init_path
            print(f"[DEBUG] Found __init__: {resolved}", file=sys.stderr)
            return resolved

        print(f"[WARN] File not found: {resolved}", file=sys.stderr)

    return None


def resolve_file_path(file_path: str) -> str:
    """
    파일 경로 정규화: 상대/절대 경로를 config.DEPENDENCY_GRAPH 키로 변환

    Windows에서 대소문자를 무시하고 경로 구분자(/, \\)를 정규화합니다.

    Args:
        file_path: 입력 경로 (상대 또는 절대)

    Returns:
        DEPENDENCY_GRAPH의 키 (절대 경로), 찾지 못하면 None
    """
    # 1. 입력 그대로 시도
    if file_path in config.DEPENDENCY_GRAPH:
        return file_path

    # 2. 경로 정규화 (슬래시 → 백슬래시)
    normalized_input = os.path.normpath(file_path)

    # 3. 정규화된 경로로 직접 매칭 시도 (대소문자 무시)
    for key in config.DEPENDENCY_GRAPH.keys():
        if os.path.normpath(key).lower() == normalized_input.lower():
            return key

    # 4. config.PROJECT_ROOT 기준 절대 경로로 변환 (상대 경로인 경우)
    if config.PROJECT_ROOT and not os.path.isabs(file_path):
        absolute_path = os.path.join(config.PROJECT_ROOT, file_path)
        absolute_path = os.path.normpath(absolute_path)

        # 대소문자 무시 매칭
        for key in config.DEPENDENCY_GRAPH.keys():
            if os.path.normpath(key).lower() == absolute_path.lower():
                return key

    # 5. Suffix 매칭 (부분 경로)
    for key in config.DEPENDENCY_GRAPH.keys():
        # 대소문자 무시 suffix 매칭
        if os.path.normpath(key).lower().endswith(normalized_input.lower()):
            return key

    return None
