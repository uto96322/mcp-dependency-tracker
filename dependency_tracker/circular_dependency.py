#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
순환 의존성 감지 모듈

이 모듈은 Tarjan's Algorithm을 사용하여 코드베이스 내의 순환 의존성을 탐지합니다.
순환 의존성은 빌드 오류와 런타임 문제를 야기할 수 있으므로 조기 발견이 중요합니다.

주요 기능:
    - Tarjan's Algorithm을 통한 강연결 요소(SCC, Strongly Connected Components) 탐지
    - 2개 이상의 파일이 서로를 참조하는 순환 구조 식별
    - 순환 의존성의 시각화 및 상세 분석

사용 예시:
    >>> from dependency_tracker.graph_builder import build_graph
    >>> graph = build_graph("./project_root")
    >>> cycles = detect_circular_dependencies(graph)
    >>> if cycles:
    ...     print(format_circular_dependencies(cycles, "./project_root"))

알고리즘 복잡도:
    - 시간 복잡도: O(V + E) (V: 파일 수, E: import 관계 수)
    - 공간 복잡도: O(V) (스택과 해시맵 저장)
"""
import sys
from typing import Dict, List, Set


def detect_circular_dependencies(graph: Dict[str, Dict]) -> List[List[str]]:
    """
    Tarjan's Algorithm을 사용하여 순환 의존성을 감지합니다.

    이 함수는 의존성 그래프를 분석하여 강연결 요소(Strongly Connected Components)를
    찾아냅니다. 크기가 2 이상인 SCC는 순환 의존성으로 간주됩니다.

    Tarjan's Algorithm 동작 원리:
        1. DFS(깊이 우선 탐색)로 그래프를 순회하며 각 노드에 인덱스 부여
        2. 각 노드의 lowlink 값을 계산 (자신과 자손이 도달할 수 있는 최소 인덱스)
        3. lowlink == index인 노드는 SCC의 루트
        4. 스택에서 루트까지의 모든 노드를 pop하여 하나의 SCC 형성

    Args:
        graph (Dict[str, Dict]): 의존성 그래프
            형식: {file_path: {"imports": [dependency_paths, ...], "exports": [...], ...}}
            예시:
                {
                    "src/a.ts": {"imports": ["src/b.ts"], "exports": ["funcA"]},
                    "src/b.ts": {"imports": ["src/a.ts"], "exports": ["funcB"]}
                }

    Returns:
        List[List[str]]: 순환 의존성 목록 (각 항목은 순환에 포함된 파일 경로 리스트)
            예시:
                [
                    ["src/a.ts", "src/b.ts"],           # 2-파일 순환
                    ["src/x.ts", "src/y.ts", "src/z.ts"] # 3-파일 순환
                ]
            빈 리스트([])는 순환 의존성이 없음을 의미합니다.

    시간 복잡도:
        O(V + E) - V: 노드(파일) 수, E: 엣지(import 관계) 수

    참고:
        - Robert Tarjan, "Depth-first search and linear graph algorithms" (1972)
        - https://en.wikipedia.org/wiki/Tarjan%27s_strongly_connected_components_algorithm
    """
    # Tarjan's Algorithm 초기화
    index_counter = [0]  # 리스트로 감싸서 내부 함수에서 수정 가능하게 함
    stack = []  # DFS 탐색 중인 노드들을 저장하는 스택
    lowlinks = {}  # 각 노드가 도달 가능한 최소 인덱스
    index = {}  # 각 노드의 방문 순서 인덱스
    on_stack = {}  # 현재 스택에 있는 노드 여부 (빠른 조회용)
    cycles = []  # 발견된 순환 의존성 목록

    def strongconnect(node: str):
        """
        Tarjan's Algorithm 핵심: 강연결 요소(SCC)를 찾는 재귀 함수

        이 함수는 DFS를 수행하면서 각 노드의 인덱스와 lowlink 값을 계산합니다.
        lowlink 값이 index 값과 같으면 해당 노드가 SCC의 루트임을 의미합니다.

        Args:
            node (str): 현재 탐색 중인 노드(파일 경로)

        동작:
            1. 노드에 고유 인덱스 부여 및 스택에 추가
            2. 모든 이웃 노드(imports)를 재귀적으로 탐색
            3. lowlink 값 업데이트 (자신과 자손이 도달 가능한 최소 인덱스)
            4. SCC 루트 발견 시 스택에서 pop하여 SCC 생성
        """
        # 1. 노드 초기화: 인덱스 할당 및 스택에 추가
        index[node] = index_counter[0]
        lowlinks[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack[node] = True

        # 2. 이웃 노드 탐색 (imports로 연결된 파일들)
        if node in graph and "imports" in graph[node]:
            for neighbor in graph[node]["imports"]:
                if neighbor not in index:
                    # 케이스 1: 아직 방문하지 않은 노드 → 재귀 탐색
                    strongconnect(neighbor)
                    # 자손의 lowlink 값을 고려하여 현재 노드의 lowlink 업데이트
                    lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
                elif on_stack.get(neighbor, False):
                    # 케이스 2: 스택에 있는 노드 → 역방향 엣지 발견 (순환!)
                    # 이웃의 인덱스를 고려하여 lowlink 업데이트
                    lowlinks[node] = min(lowlinks[node], index[neighbor])

        # 3. 강연결 요소(SCC) 발견: lowlink == index인 경우
        if lowlinks[node] == index[node]:
            scc = []
            # 스택에서 현재 노드까지 모든 노드를 pop → 하나의 SCC
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == node:
                    break

            # 4. 크기가 2 이상인 SCC만 순환 의존성으로 간주
            # (크기 1은 자기 자신만 있는 경우로 순환이 아님)
            if len(scc) > 1:
                cycles.append(scc)

    # 모든 노드에 대해 Tarjan's Algorithm 실행
    # (연결되지 않은 컴포넌트도 처리하기 위해)
    for node in graph:
        if node not in index:
            strongconnect(node)

    return cycles


def format_circular_dependencies(cycles: List[List[str]], project_root: str) -> str:
    """
    순환 의존성을 사람이 읽기 쉬운 마크다운 형식으로 포맷합니다.

    이 함수는 detect_circular_dependencies()의 결과를 받아 각 순환 그룹에 대해
    파일 목록과 순환 경로를 시각화하고, 해결 방법을 제안합니다.

    Args:
        cycles (List[List[str]]): detect_circular_dependencies()의 반환값
            각 항목은 순환에 포함된 파일 경로 리스트
        project_root (str): 프로젝트 루트 디렉토리 경로
            상대 경로 변환에 사용됨 (예: "/home/user/project")

    Returns:
        str: 마크다운 형식의 포맷된 문자열
            - 순환이 없으면 "✅ 순환 의존성 없음" 반환
            - 순환이 있으면 각 순환 그룹의 상세 정보와 해결 방법 반환

    예시 출력:
        ⚠️ 2개 순환 의존성 발견

        ## 순환 1 (2개 파일)

        - src/a.ts
        - src/b.ts

        **순환 경로**:
        a.ts → b.ts → a.ts

        ---
        **권장 조치**:
        1. 공통 인터페이스 분리
        2. Dependency Injection 사용
        3. Barrel 파일로 재구성
    """
    import os

    # 순환 의존성이 없는 경우 성공 메시지 반환
    if not cycles:
        return "✅ 순환 의존성 없음"

    # 헤더: 발견된 순환 의존성 총 개수
    result = f"⚠️ {len(cycles)}개 순환 의존성 발견\n\n"

    # 각 순환 그룹에 대한 상세 정보 출력
    for i, cycle in enumerate(cycles, 1):
        result += f"## 순환 {i} ({len(cycle)}개 파일)\n\n"

        # 순환에 포함된 파일 목록 (상대 경로로 표시)
        for file in cycle:
            rel_path = os.path.relpath(file, project_root)
            result += f"- {rel_path}\n"

        # 순환 경로 시각화 (파일명만 사용하여 간결하게)
        # 예: a.ts → b.ts → c.ts → a.ts (시작점으로 돌아옴을 명시)
        result += "\n**순환 경로**:\n"
        cycle_visual = " → ".join([os.path.basename(f) for f in cycle])
        cycle_visual += f" → {os.path.basename(cycle[0])}"  # 시작점으로 돌아감
        result += f"{cycle_visual}\n\n"

    # 순환 의존성 해결을 위한 권장 조치 안내
    result += "---\n"
    result += "**권장 조치**:\n"
    result += "1. 공통 인터페이스 분리 - 공유 타입/인터페이스를 별도 파일로 추출\n"
    result += "2. Dependency Injection 사용 - 생성자/함수 파라미터로 의존성 주입\n"
    result += "3. Barrel 파일로 재구성 - index.ts를 통한 re-export 패턴 활용\n"

    return result


def get_cycle_details(cycle: List[str], graph: Dict[str, Dict], project_root: str) -> str:
    """
    특정 순환 의존성에 대한 상세 분석 정보를 제공합니다.

    이 함수는 순환에 포함된 각 파일의 import/export 정보를 분석하여
    순환 의존성의 원인을 파악하는 데 도움을 줍니다.

    Args:
        cycle (List[str]): 순환에 포함된 파일 경로 목록
            예: ["src/a.ts", "src/b.ts"]
        graph (Dict[str, Dict]): 의존성 그래프
            형식: {file_path: {"imports": [...], "exports": [...], ...}}
        project_root (str): 프로젝트 루트 디렉토리 경로
            상대 경로 변환에 사용됨

    Returns:
        str: 마크다운 형식의 상세 분석 문자열
            각 파일별로:
            - 순환 내에서 import하는 파일 목록
            - Export하는 심볼 목록 (최대 10개)

    예시 출력:
        # 순환 의존성 상세 (2개 파일)

        ## 1. src/a.ts

        **Import (순환 내)**:
        - src/b.ts

        **Exports** (2개):
        - funcA
        - ClassA

        ## 2. src/b.ts

        **Import (순환 내)**:
        - src/a.ts

        **Exports** (1개):
        - funcB

    사용 시나리오:
        순환 의존성을 해결하기 위해 각 파일이 무엇을 import/export하는지
        파악하여 공통 인터페이스 분리나 구조 개선의 기반 정보로 활용
    """
    import os

    # 헤더: 순환에 포함된 파일 개수
    result = f"# 순환 의존성 상세 ({len(cycle)}개 파일)\n\n"

    # 각 파일에 대한 상세 분석
    for i, file in enumerate(cycle):
        rel_path = os.path.relpath(file, project_root)
        result += f"## {i + 1}. {rel_path}\n\n"

        # 그래프에서 파일 정보 조회
        if file in graph:
            data = graph[file]

            # 1. 순환 내에서 import하는 파일 목록
            # (순환의 원인이 되는 import 관계만 필터링)
            imports_in_cycle = [f for f in data.get("imports", []) if f in cycle]
            if imports_in_cycle:
                result += "**Import (순환 내)**:\n"
                for imp in imports_in_cycle:
                    imp_rel = os.path.relpath(imp, project_root)
                    result += f"- {imp_rel}\n"
                result += "\n"

            # 2. Export하는 심볼 목록
            # (다른 파일이 무엇을 import하려고 하는지 파악)
            exports = data.get("exports", [])
            if exports:
                result += f"**Exports** ({len(exports)}개):\n"
                # 가독성을 위해 최대 10개만 표시
                for exp in exports[:10]:
                    result += f"- {exp}\n"
                # 10개 초과 시 나머지 개수 표시
                if len(exports) > 10:
                    result += f"- ... ({len(exports) - 10}개 더)\n"
                result += "\n"

    return result
