#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
의존성 그래프 빌드 및 분석

이 모듈은 프로젝트 전체의 파일 간 의존성을 분석하고 그래프를 구축합니다:
- 파일 스캔 및 imports/exports 추출
- 의존성 관계 계산
- Barrel 파일 감지
- Re-export 체인 추적
"""
import os
import sys
from pathlib import Path
from typing import Dict, List, Set
import time

from . import config
from .parser import parse_imports
from .path_resolver import load_tsconfig_paths, resolve_import_path


def build_dependency_graph(project_root: str, incremental: bool = True) -> Dict[str, Dict]:
    """
    프로젝트 전체 의존성 그래프 생성 (Phase 3: 증분 빌드)

    Args:
        project_root: 프로젝트 루트 경로
        incremental: 증분 빌드 사용 (기본값: True)

    Returns:
        {
            "src/services/user.ts": {
                "imports": ["src/lib/db.ts", "src/types/user.ts"],
                "exports": ["getUserById", "User"],
                "dependents": ["src/controllers/user.ts", "src/admin/users.ts"],
                "mtime": 1699999999.0
            }
        }
    """

    start_time = time.time()

    # ⭐ Phase 2-1: tsconfig paths 로드
    config.PATH_MAPPINGS = load_tsconfig_paths(project_root)
    print(f"[INFO] Loaded {len(config.PATH_MAPPINGS)} path mappings", file=sys.stderr)

    # 모든 TypeScript/JavaScript/Python 파일 스캔
    extensions = ['.ts', '.tsx', '.js', '.jsx', '.py']
    files = []

    for ext in extensions:
        files.extend(Path(project_root).rglob(f'*{ext}'))

    # 경로 정규화 및 필터링
    all_files = set()
    for file_path in files:
        file_str = os.path.normpath(str(file_path))
        # node_modules, dist, build 제외
        if 'node_modules' not in file_str and 'dist' not in file_str and 'build' not in file_str:
            all_files.add(file_str)

    # ⭐ Phase 3: 증분 빌드 (변경된 파일만 재파싱)
    graph = {}
    files_to_parse = []
    reused_count = 0

    if incremental and config.DEPENDENCY_GRAPH:
        # 기존 그래프가 있으면 증분 업데이트
        print(f"[INFO] Incremental build: checking {len(all_files)} files...", file=sys.stderr)

        for file_str in all_files:
            if file_str in config.DEPENDENCY_GRAPH:
                # 파일 mtime 확인
                try:
                    current_mtime = os.path.getmtime(file_str)
                    cached_mtime = config.DEPENDENCY_GRAPH[file_str].get("mtime", 0)

                    if current_mtime == cached_mtime:
                        # 변경 없음 → 재사용
                        graph[file_str] = config.DEPENDENCY_GRAPH[file_str].copy()
                        reused_count += 1
                    else:
                        # 변경됨 → 재파싱 필요
                        files_to_parse.append(file_str)
                except:
                    files_to_parse.append(file_str)
            else:
                # 새 파일 → 파싱 필요
                files_to_parse.append(file_str)

        # 삭제된 파일 제거
        for file_str in list(config.DEPENDENCY_GRAPH.keys()):
            if file_str not in all_files:
                print(f"[INFO] Removed deleted file: {os.path.basename(file_str)}", file=sys.stderr)

        print(f"[INFO] Reused {reused_count} files, parsing {len(files_to_parse)} changed files", file=sys.stderr)
    else:
        # 전체 빌드
        files_to_parse = list(all_files)
        print(f"[INFO] Full build: parsing {len(files_to_parse)} files...", file=sys.stderr)

    # 파싱 수행 (순차 - GIL 때문에 병렬 처리 효과 없음)
    for i, file_str in enumerate(files_to_parse):
        try:
            if (i + 1) % 100 == 0:
                print(f"[INFO] Parsed {i + 1}/{len(files_to_parse)} files...", file=sys.stderr)

            parsed = parse_imports(file_str)
            mtime = os.path.getmtime(file_str)

            graph[file_str] = {
                "imports": [],
                "exports": parsed["exports"],
                "named_imports": {},
                "dependents": [],
                "mtime": mtime
            }

            # import 경로를 절대 경로로 변환
            for import_path in parsed["imports"]:
                resolved = resolve_import_path(import_path, file_str, project_root)
                if resolved:
                    graph[file_str]["imports"].append(resolved)
                    if import_path in parsed["named_imports"]:
                        graph[file_str]["named_imports"][resolved] = parsed["named_imports"][import_path]
        except Exception as e:
            print(f"[WARN] Failed to parse {file_str}: {e}", file=sys.stderr)

    # dependents 계산 (전체 그래프 대상)
    for file_path in graph:
        graph[file_path]["dependents"] = []

    for file_path, data in graph.items():
        for imported_file in data["imports"]:
            if imported_file in graph:
                graph[imported_file]["dependents"].append(file_path)

    elapsed = time.time() - start_time
    print(f"[INFO] Graph built in {elapsed:.2f}s ({len(graph)} files)", file=sys.stderr)

    return graph


def is_barrel_file(file_path: str) -> bool:
    """
    Barrel 파일 (index.ts, index.tsx 등) 패턴인지 확인

    Barrel 파일은 여러 모듈을 re-export하는 중간 파일로,
    진짜 간접 의존성을 발생시킬 수 있습니다.

    Returns:
        True if file is a barrel file (index.ts, index.tsx, etc.)
    """
    path = Path(file_path)
    filename = path.stem  # 확장자 제외한 파일명

    # index 파일들
    if filename == 'index':
        return True

    # _barrel, barrel 같은 명시적 패턴
    if 'barrel' in filename.lower():
        return True

    return False


def has_reexport_pattern(file_path: str, imported_file: str) -> bool:
    """
    file_path가 imported_file을 re-export하는지 확인

    Re-export 패턴:
    1. import { X } from './imported_file'
       export { X }  (또는 export X)

    2. export * from './imported_file'

    3. export { X } from './imported_file'

    Args:
        file_path: 확인할 파일
        imported_file: import된 파일

    Returns:
        True if re-export pattern detected
    """
    if file_path not in config.DEPENDENCY_GRAPH:
        return False

    data = config.DEPENDENCY_GRAPH[file_path]
    imports = data.get("imports", [])
    exports = data.get("exports", [])
    named_imports = data.get("named_imports", {})

    # imported_file을 import하지 않으면 re-export 불가
    if imported_file not in imports:
        return False

    # Barrel 파일은 re-export로 간주
    if is_barrel_file(file_path):
        return True

    # imported_file에서 가져온 이름들
    imported_names = named_imports.get(imported_file, [])

    # imported_names와 exports의 교집합이 있으면 re-export
    common = set(imported_names) & set(exports)
    if common:
        print(f"[DEBUG] Re-export detected: {file_path} re-exports {list(common)} from {imported_file}", file=sys.stderr)
        return True

    return False


def expand_reexport_chain(file_path: str, max_depth: int = 10) -> Set[str]:
    """
    Re-export 체인을 재귀적으로 확장하여 진짜 간접 dependent만 찾기 (Phase 2-3 개선)

    **수정 사항 (버그 #1 해결)**:
    - 이전: "A의 dependent의 dependent"를 무조건 추가 (잘못됨)
    - 현재: "A를 re-export하는 B를 import하는 C만" 추가 (정확함)

    **예시**:
    - ❌ 잘못된 케이스:
      message-store ← learning-session-store ← timer-service
      (timer-service는 message-store를 모름 → 간접 dependent 아님!)

    - ✅ 올바른 케이스:
      message-store ← barrel/index.ts (re-export) ← other-file
      (barrel이 message-store를 re-export → other-file은 간접 dependent!)

    Args:
        file_path: 시작 파일 경로
        max_depth: 최대 재귀 깊이 (무한 루프 방지)

    Returns:
        진짜 간접 dependent만 포함한 집합
    """
    visited = set()
    all_dependents = set()

    def traverse(current_file: str, depth: int):
        # 무한 루프 방지
        if depth > max_depth or current_file in visited:
            return

        visited.add(current_file)

        if current_file not in config.DEPENDENCY_GRAPH:
            return

        # 현재 파일의 직접 dependents
        direct_dependents = config.DEPENDENCY_GRAPH[current_file].get("dependents", [])

        for dependent in direct_dependents:
            # 직접 dependent는 항상 추가
            all_dependents.add(dependent)

            # ✅ Re-export 여부 확인 (핵심 수정!)
            if has_reexport_pattern(dependent, current_file):
                # 진짜 re-export인 경우에만 체인 계속 추적
                print(f"[DEBUG] Valid re-export chain: {current_file} → {dependent} (depth {depth})", file=sys.stderr)
                traverse(dependent, depth + 1)
            else:
                # Re-export 아니면 체인 중단
                print(f"[DEBUG] Chain stopped (no re-export): {current_file} → {dependent}", file=sys.stderr)

    traverse(file_path, 0)
    return all_dependents


def calculate_all_dependents(file_path: str) -> List[str]:
    """
    직접 + 간접 (re-export 체인) dependent 모두 계산 (Phase 2-4)

    Returns:
        정렬된 전체 dependent 리스트
    """
    # 1. 직접 dependents
    if file_path not in config.DEPENDENCY_GRAPH:
        return []

    direct_dependents = set(config.DEPENDENCY_GRAPH[file_path].get("dependents", []))

    # 2. Re-export 체인 확장
    all_from_chain = expand_reexport_chain(file_path)

    # 3. 합치기 (중복 제거)
    all_dependents = direct_dependents | all_from_chain

    return sorted(list(all_dependents))
