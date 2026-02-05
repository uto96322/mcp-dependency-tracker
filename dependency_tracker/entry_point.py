#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entry Point 자동 식별

프로젝트의 진입점을 자동으로 감지합니다:
- Next.js: app/page.tsx, pages/*.tsx
- Node.js: src/index.ts, server.ts
- Heuristic: dependents=0 + imports>10
"""
import os
import re
from typing import Dict, List


def identify_entry_points(graph: Dict[str, Dict], project_root: str) -> List[Dict]:
    """
    Entry Point 자동 식별

    Args:
        graph: 의존성 그래프
        project_root: 프로젝트 루트

    Returns:
        Entry point 목록:
        [
            {
                "file": "app/page.tsx",
                "type": "Next.js App Router Page",
                "dependents": 0,
                "imports": 15,
                "score": 100
            }
        ]
    """
    entry_points = []

    # 1. Next.js/React 진입점 패턴
    nextjs_patterns = [
        (r'app.*page\.tsx?$', 'Next.js App Router Page', 100),
        (r'app.*layout\.tsx?$', 'Next.js App Layout', 90),
        (r'pages.*index\.tsx?$', 'Next.js Pages Router Index', 95),
        (r'pages/.*\.tsx?$', 'Next.js Pages Router', 80),
        (r'src/index\.tsx?$', 'React Entry Point', 90),
        (r'src/App\.tsx?$', 'React App Component', 85),
    ]

    # 2. Node.js 진입점 패턴
    nodejs_patterns = [
        (r'src/(index|server|app|main)\.ts$', 'Node.js Main Entry', 95),
        (r'bin/.*', 'CLI Entry Point', 90),
        (r'server\.ts$', 'Server Entry', 90),
        (r'index\.(ts|js)$', 'Package Entry', 70),
    ]

    # 3. API 라우트 패턴
    api_patterns = [
        (r'app/api/.*route\.ts$', 'Next.js API Route', 60),
        (r'pages/api/.*\.ts$', 'Next.js API (Pages)', 60),
    ]

    all_patterns = nextjs_patterns + nodejs_patterns + api_patterns

    # 각 파일 검사
    for file_path, data in graph.items():
        rel_path = os.path.relpath(file_path, project_root)

        # 패턴 매칭
        matched = False
        for pattern, entry_type, base_score in all_patterns:
            if re.search(pattern, rel_path):
                dependents_count = len(data.get("dependents", []))
                imports_count = len(data.get("imports", []))

                # 점수 계산 (패턴 점수 + 보너스)
                score = base_score

                # dependent가 0개면 진짜 Entry Point일 가능성 높음
                if dependents_count == 0:
                    score += 20

                # import가 많으면 중요한 파일
                if imports_count > 10:
                    score += 10
                elif imports_count > 5:
                    score += 5

                entry_points.append({
                    "file": rel_path,
                    "type": entry_type,
                    "dependents": dependents_count,
                    "imports": imports_count,
                    "score": min(score, 100)  # 최대 100점
                })
                matched = True
                break

        # 4. Heuristic: 패턴 매칭 안 되지만 Entry Point일 가능성
        if not matched:
            dependents_count = len(data.get("dependents", []))
            imports_count = len(data.get("imports", []))

            # dependent 0개 + import 10개 이상 → 의심
            if dependents_count == 0 and imports_count >= 10:
                # 하지만 node_modules, test, spec 제외
                if 'test' not in rel_path.lower() and 'spec' not in rel_path.lower():
                    entry_points.append({
                        "file": rel_path,
                        "type": "Inferred Entry (no dependents)",
                        "dependents": 0,
                        "imports": imports_count,
                        "score": 50 + min(imports_count, 30)  # 50-80점
                    })

    # 점수 순으로 정렬
    entry_points.sort(key=lambda x: x["score"], reverse=True)

    return entry_points


def format_entry_points(entry_points: List[Dict], top_n: int = 20) -> str:
    """
    Entry Point 목록을 읽기 쉽게 포맷

    Args:
        entry_points: identify_entry_points() 결과
        top_n: 상위 N개만 표시

    Returns:
        포맷된 문자열
    """
    if not entry_points:
        return "❌ Entry Point를 찾을 수 없습니다."

    result = f"# Entry Points ({len(entry_points)}개 발견)\n\n"
    result += f"**상위 {min(top_n, len(entry_points))}개 표시**\n\n"

    # 타입별 그룹화
    by_type = {}
    for ep in entry_points[:top_n]:
        entry_type = ep["type"]
        if entry_type not in by_type:
            by_type[entry_type] = []
        by_type[entry_type].append(ep)

    # 타입별 출력
    for entry_type, eps in by_type.items():
        result += f"## {entry_type} ({len(eps)}개)\n\n"

        for ep in eps:
            result += f"### {ep['file']}\n"
            result += f"- **Score**: {ep['score']}/100\n"
            result += f"- **Dependents**: {ep['dependents']}\n"
            result += f"- **Imports**: {ep['imports']}\n"
            result += "\n"

    result += "---\n"
    result += "**해석**:\n"
    result += "- **Score**: 높을수록 Entry Point일 가능성 높음\n"
    result += "- **Dependents 0**: 아무도 import하지 않음 → Entry Point\n"
    result += "- **Imports 많음**: 많은 모듈을 사용 → 중요한 파일\n"

    return result


def get_entry_point_details(file_path: str, graph: Dict[str, Dict], project_root: str) -> str:
    """
    특정 Entry Point의 상세 정보

    Args:
        file_path: Entry Point 파일 경로
        graph: 의존성 그래프
        project_root: 프로젝트 루트

    Returns:
        상세 정보 문자열
    """
    if file_path not in graph:
        return f"❌ 파일을 찾을 수 없습니다: {file_path}"

    data = graph[file_path]
    rel_path = os.path.relpath(file_path, project_root)

    result = f"# Entry Point 상세: {rel_path}\n\n"

    # 기본 정보
    result += "## 기본 정보\n"
    result += f"- **Dependents**: {len(data.get('dependents', []))}\n"
    result += f"- **Imports**: {len(data.get('imports', []))}\n"
    result += f"- **Exports**: {len(data.get('exports', []))}\n"
    result += "\n"

    # Import 목록
    imports = data.get("imports", [])
    if imports:
        result += f"## Imports ({len(imports)}개)\n\n"
        for imp in imports[:20]:
            imp_rel = os.path.relpath(imp, project_root)
            result += f"- {imp_rel}\n"
        if len(imports) > 20:
            result += f"- ... ({len(imports) - 20}개 더)\n"
        result += "\n"

    # Export 목록
    exports = data.get("exports", [])
    if exports:
        result += f"## Exports ({len(exports)}개)\n\n"
        for exp in exports[:20]:
            result += f"- `{exp}`\n"
        if len(exports) > 20:
            result += f"- ... ({len(exports) - 20}개 더)\n"
        result += "\n"

    return result
