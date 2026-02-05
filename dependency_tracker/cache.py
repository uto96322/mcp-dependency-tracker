#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
의존성 그래프 캐시 관리

이 모듈은 의존성 그래프를 파일 캐시로 저장하고 불러옵니다.
캐시를 사용하면 서버 재시작 시 빠르게 의존성 그래프를 복원할 수 있습니다.
"""
import os
import sys
import json
import time

from . import config  # 모듈 전체 import로 변경
from .path_resolver import load_tsconfig_paths
from .dependency_graph import build_dependency_graph


def _convert_to_relative_paths(graph: dict, project_root: str) -> dict:
    """
    의존성 그래프의 절대 경로를 상대 경로로 변환 (캐시 저장용)

    Args:
        graph: 의존성 그래프 (절대 경로)
        project_root: 프로젝트 루트

    Returns:
        상대 경로로 변환된 그래프
    """
    relative_graph = {}

    for abs_path, data in graph.items():
        # 파일 경로를 상대 경로로 변환
        rel_path = os.path.relpath(abs_path, project_root)

        # imports, dependents도 상대 경로로 변환
        relative_graph[rel_path] = {
            "imports": [os.path.relpath(p, project_root) for p in data.get("imports", [])],
            "exports": data.get("exports", []),
            "named_imports": {
                os.path.relpath(k, project_root): v
                for k, v in data.get("named_imports", {}).items()
            },
            "dependents": [os.path.relpath(p, project_root) for p in data.get("dependents", [])]
        }

    return relative_graph


def _convert_to_absolute_paths(graph: dict, project_root: str) -> dict:
    """
    의존성 그래프의 상대 경로를 절대 경로로 변환 (캐시 로드용)

    Args:
        graph: 의존성 그래프 (상대 경로)
        project_root: 프로젝트 루트

    Returns:
        절대 경로로 변환된 그래프
    """
    absolute_graph = {}

    for rel_path, data in graph.items():
        # 파일 경로를 절대 경로로 변환
        abs_path = os.path.normpath(os.path.join(project_root, rel_path))

        # imports, dependents도 절대 경로로 변환
        absolute_graph[abs_path] = {
            "imports": [
                os.path.normpath(os.path.join(project_root, p))
                for p in data.get("imports", [])
            ],
            "exports": data.get("exports", []),
            "named_imports": {
                os.path.normpath(os.path.join(project_root, k)): v
                for k, v in data.get("named_imports", {}).items()
            },
            "dependents": [
                os.path.normpath(os.path.join(project_root, p))
                for p in data.get("dependents", [])
            ]
        }

    return absolute_graph


def load_dependency_graph_cache():
    """서버 시작 시 캐시된 의존성 그래프 자동 로드"""
    # 현재 디렉터리에서 캐시 파일 찾기
    cache_file = ".dependency_graph_cache.json"
    if not os.path.exists(cache_file):
        print("[INFO] No dependency graph cache found. Run build_dependency_graph first.", file=sys.stderr)
        return

    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)

        config.PROJECT_ROOT = cache_data.get("project_root")
        relative_graph = cache_data.get("graph", {})

        # ⭐ 상대 경로 → 절대 경로 변환
        config.DEPENDENCY_GRAPH = _convert_to_absolute_paths(relative_graph, config.PROJECT_ROOT)

        # ⭐ Bug Fix: PATH_MAPPINGS 복원
        if config.PROJECT_ROOT:
            config.PATH_MAPPINGS = load_tsconfig_paths(config.PROJECT_ROOT)
            print(f"[INFO] Loaded {len(config.PATH_MAPPINGS)} path mappings from tsconfig.json", file=sys.stderr)

        total_files = len(config.DEPENDENCY_GRAPH)
        print(f"[INFO] Loaded dependency graph from cache: {total_files} files", file=sys.stderr)
        print(f"[INFO] Project root: {config.PROJECT_ROOT}", file=sys.stderr)
    except Exception as e:
        print(f"[WARN] Failed to load cache: {e}", file=sys.stderr)


def ensure_dependency_graph(project_root: str = None) -> bool:
    """
    의존성 그래프 자동 빌드 (캐시 없거나 오래된 경우)

    Args:
        project_root: 프로젝트 루트 경로 (None이면 현재 디렉토리)

    Returns:
        True if dependency graph is ready, False if failed
    """
    # 1. 이미 빌드되어 있으면 OK
    if config.DEPENDENCY_GRAPH:
        print("[DEBUG] Dependency graph already loaded", file=sys.stderr)
        return True

    # 2. project_root 결정
    if not project_root:
        # 현재 디렉토리 또는 캐시에서 읽기
        cache_file = ".dependency_graph_cache.json"
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                project_root = cache_data.get("project_root")
            except:
                pass

        if not project_root:
            # ⭐ 자동 감지: package.json 또는 tsconfig.json 찾기
            cwd = os.getcwd()

            # 1단계: 하위 디렉토리에서 먼저 찾기 (우선순위)
            # 이유: 루트에 monorepo package.json이 있을 수 있지만,
            #      실제 프로젝트는 하위 디렉토리 (my-app 등)
            subdirs_with_config = []
            for subdir in os.listdir(cwd):
                subdir_path = os.path.join(cwd, subdir)
                if os.path.isdir(subdir_path) and not subdir.startswith('.'):
                    if os.path.exists(os.path.join(subdir_path, "package.json")) and os.path.exists(os.path.join(subdir_path, "tsconfig.json")):
                        subdirs_with_config.append((subdir, subdir_path))

            # tsconfig.json + package.json 둘 다 있는 디렉토리 우선
            if subdirs_with_config:
                # 이름으로 정렬해서 첫 번째 선택 (일관성)
                subdirs_with_config.sort()
                selected_subdir, selected_path = subdirs_with_config[0]
                project_root = selected_path
                print(f"[INFO] Auto-detected project root: {selected_subdir}", file=sys.stderr)

            # 2단계: 못 찾으면 현재 디렉토리에서 찾기
            elif os.path.exists(os.path.join(cwd, "package.json")) or os.path.exists(os.path.join(cwd, "tsconfig.json")):
                project_root = cwd

            # 3단계: 그래도 못 찾으면 현재 디렉토리 사용
            else:
                project_root = cwd

    config.PROJECT_ROOT = project_root

    # 3. 캐시 파일 확인
    cache_file = os.path.join(project_root, ".dependency_graph_cache.json")

    if os.path.exists(cache_file):
        # 캐시 나이 확인 (1시간 = 3600초)
        cache_age = os.path.getmtime(cache_file)
        current_time = time.time()
        age_seconds = current_time - cache_age

        # 1시간 이내면 캐시 사용
        if age_seconds < 3600:
            print(f"[INFO] Loading from cache (age: {int(age_seconds)}s)", file=sys.stderr)
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                config.PROJECT_ROOT = cache_data.get("project_root")
                relative_graph = cache_data.get("graph", {})

                # ⭐ 상대 경로 → 절대 경로 변환
                config.DEPENDENCY_GRAPH = _convert_to_absolute_paths(relative_graph, config.PROJECT_ROOT)

                if config.PROJECT_ROOT:
                    config.PATH_MAPPINGS = load_tsconfig_paths(config.PROJECT_ROOT)
                print(f"[INFO] Loaded {len(config.DEPENDENCY_GRAPH)} files from cache", file=sys.stderr)
                return bool(config.DEPENDENCY_GRAPH)
            except Exception as e:
                print(f"[WARN] Failed to load cache: {e}, rebuilding...", file=sys.stderr)
        else:
            print(f"[INFO] Cache outdated (age: {int(age_seconds)}s), rebuilding...", file=sys.stderr)
    else:
        print(f"[INFO] No cache found, building dependency graph...", file=sys.stderr)

    # 4. 의존성 그래프 빌드
    try:
        config.DEPENDENCY_GRAPH = build_dependency_graph(project_root)

        # 5. 캐시 저장 (상대 경로로 변환)
        try:
            # ⭐ 절대 경로 → 상대 경로 변환
            relative_graph = _convert_to_relative_paths(config.DEPENDENCY_GRAPH, project_root)

            cache_data = {
                "project_root": project_root,
                "graph": relative_graph
            }
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            print(f"[INFO] Saved dependency graph cache: {len(config.DEPENDENCY_GRAPH)} files (relative paths)", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] Failed to save cache: {e}", file=sys.stderr)

        return True
    except Exception as e:
        print(f"[ERROR] Failed to build dependency graph: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False
