#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dependency Tracker MCP Server - 메인 진입점

이 모듈은 MCP (Model Context Protocol) 서버의 메인 진입점입니다.
8개의 도구를 제공하여 TypeScript/JavaScript 프로젝트의 의존성을 추적하고,
Breaking Change를 감지하며, 필드 추적 및 이름 변경을 지원합니다.
"""
import asyncio
import os
import sys
import json
from typing import Any

# MCP imports
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# 내부 모듈 imports
from . import config  # 모듈 전체 import
from .dependency_graph import build_dependency_graph, calculate_all_dependents
from .breaking_changes import detect_breaking_changes, suggest_cascade_fix
from .field_tracker import track_field_usage
from .rename_refactor import rename_symbol
from .path_resolver import resolve_file_path
from .cache import load_dependency_graph_cache, ensure_dependency_graph, _convert_to_relative_paths
from .circular_dependency import detect_circular_dependencies, format_circular_dependencies
from .entry_point import identify_entry_points, format_entry_points

# Server instance
app = Server("dependency-tracker")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """사용 가능한 도구 목록"""
    return [
        Tool(
            name="build_dependency_graph",
            description="프로젝트 전체 의존성 그래프 생성 (TypeScript/JavaScript)",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_root": {
                        "type": "string",
                        "description": "프로젝트 루트 경로"
                    }
                },
                "required": ["project_root"]
            }
        ),
        Tool(
            name="check_file_dependencies",
            description="""Check file imports, exports, and dependents BEFORE modifying files.

WHEN TO USE (MANDATORY per CLAUDE.md):
- BEFORE editing ANY file with >50 lines
- BEFORE renaming or moving files
- AFTER adding new exports to understand impact scope

WHY: Prevents breaking changes by revealing who depends on this file.
Example: Before editing chat-api.ts, check which files import it.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "파일 절대 경로"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="detect_breaking_changes",
            description="""Detect breaking changes BEFORE removing exports from a file.

WHEN TO USE (MANDATORY per CLAUDE.md):
- BEFORE deleting exported functions/types/interfaces
- AFTER modifying public API surface
- When asked to "clean up" or "refactor" exports

WHY: Shows which files will break if you remove this export. Save hours debugging.
Example: Before removing 'useChatStore', detect if 14 files still import it.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "파일 절대 경로"
                    },
                    "old_exports": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "이전 exports 목록"
                    },
                    "new_exports": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "새로운 exports 목록"
                    }
                },
                "required": ["file_path", "old_exports", "new_exports"]
            }
        ),
        Tool(
            name="suggest_cascade_fix",
            description="Breaking Change에 대한 Cascade Fix 제안",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "파일 절대 경로"
                    },
                    "removed_exports": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "제거된 exports 목록"
                    }
                },
                "required": ["file_path", "removed_exports"]
            }
        ),
        Tool(
            name="visualize_dependencies",
            description="의존성 그래프 Mermaid 다이어그램 생성",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "중심 파일 경로 (선택사항)"
                    },
                    "depth": {
                        "type": "number",
                        "description": "탐색 깊이 (기본 2)",
                        "default": 2
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="find_dead_code",
            description="사용하지 않는 export 자동 감지 (Phase 3)",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="track_field_usage",
            description="""Track all usages of a field/property BEFORE renaming or removing it.

WHEN TO USE (MANDATORY per CLAUDE.md):
- BEFORE renaming any interface/type field
- BEFORE removing a field from a type
- When asked to change field names

WHY: Shows ALL places using this field (14+ files typical). Missing one = runtime error.
Example: Before renaming 'studentName' to 'userName', track to find all 14 usages.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "필드가 정의된 파일 경로"
                    },
                    "field_name": {
                        "type": "string",
                        "description": "추적할 필드 이름 (예: studentName)"
                    }
                },
                "required": ["file_path", "field_name"]
            }
        ),
        Tool(
            name="rename_symbol",
            description="심볼의 모든 참조를 자동으로 이름 변경 (Phase 3: Rename Refactoring)",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "심볼이 정의된 파일 경로"
                    },
                    "old_name": {
                        "type": "string",
                        "description": "기존 이름 (예: studentName)"
                    },
                    "new_name": {
                        "type": "string",
                        "description": "새로운 이름 (예: userName)"
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "True: 미리보기만, False: 실제 파일 수정",
                        "default": True
                    }
                },
                "required": ["file_path", "old_name", "new_name"]
            }
        ),
        Tool(
            name="detect_circular_dependencies",
            description="""순환 의존성 감지 (Tarjan's Algorithm)

순환 의존성은 빌드 오류와 런타임 문제를 일으킬 수 있습니다.

예시:
- file-a.ts ← file-b.ts ← file-a.ts (순환!)
- 3개 이상 파일의 순환도 감지

권장 사용 시점:
- 프로젝트 초기 설정 시
- 리팩토링 전후
- 빌드 문제 디버깅 시""",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="identify_entry_points",
            description="""프로젝트 Entry Point 자동 식별

다양한 패턴으로 Entry Point를 감지합니다:
- Next.js: app/page.tsx, pages/*.tsx
- Node.js: src/index.ts, server.ts
- API Routes: app/api/*/route.ts
- Heuristic: dependents=0 + imports>10

권장 사용 시점:
- 프로젝트 구조 파악 시
- 리팩토링 시작점 찾기
- 새 팀원 온보딩""",
            inputSchema={
                "type": "object",
                "properties": {
                    "top_n": {
                        "type": "number",
                        "description": "상위 N개만 표시 (기본값: 20)",
                        "default": 20
                    }
                },
                "required": []
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """도구 실행"""
    if name == "build_dependency_graph":
        project_root = arguments.get("project_root")
        config.PROJECT_ROOT = project_root

        print(f"[INFO] Building dependency graph for: {project_root}", file=sys.stderr)
        config.DEPENDENCY_GRAPH = build_dependency_graph(project_root)

        total_files = len(config.DEPENDENCY_GRAPH)
        total_deps = sum(len(data["dependents"]) for data in config.DEPENDENCY_GRAPH.values())

        # 파일로 저장 (다음 서버 시작 시 자동 로드, 상대 경로로 변환)
        cache_file = os.path.join(project_root, ".dependency_graph_cache.json")
        try:
            # ⭐ 절대 경로 → 상대 경로 변환
            relative_graph = _convert_to_relative_paths(config.DEPENDENCY_GRAPH, project_root)

            cache_data = {
                "project_root": project_root,
                "graph": relative_graph
            }
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            print(f"[INFO] Saved dependency graph to: {cache_file} (relative paths)", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] Failed to save cache: {e}", file=sys.stderr)

        output = f"의존성 그래프 생성 완료\n\n"
        output += f"- 분석 파일: {total_files}개\n"
        output += f"- 총 의존 관계: {total_deps}개\n\n"
        output += f"사용 방법:\n"
        output += f"- check_file_dependencies: 파일별 의존성 조회\n"
        output += f"- detect_breaking_changes: Breaking Change 감지\n"

        return [TextContent(type="text", text=output)]

    elif name == "check_file_dependencies":
        # ⭐ 자동 빌드: 캐시 없거나 오래되었으면 자동 빌드
        if not ensure_dependency_graph():
            return [TextContent(type="text", text=f"의존성 그래프를 빌드할 수 없습니다. 프로젝트 루트에서 실행하세요.")]

        file_path = arguments.get("file_path")
        resolved_path = resolve_file_path(file_path)

        if not resolved_path:
            return [TextContent(type="text", text=f"파일을 찾을 수 없습니다: {file_path}")]

        data = config.DEPENDENCY_GRAPH[resolved_path]

        # ⭐ Phase 2-5: 직접/간접 dependent 구분
        direct_dependents = data.get("dependents", [])
        all_dependents = calculate_all_dependents(resolved_path)
        indirect_dependents = [d for d in all_dependents if d not in direct_dependents]

        # 위험도 계산
        total_count = len(all_dependents)
        if total_count >= 10:
            risk = "HIGH"
            risk_emoji = "WARNING"
        elif total_count >= 3:
            risk = "MEDIUM"
            risk_emoji = "WARNING"
        else:
            risk = "LOW"
            risk_emoji = "OK"

        output = f"## {os.path.basename(file_path)} 의존성 정보\n\n"
        output += f"### Imports ({len(data['imports'])}개)\n"
        for imp in data['imports']:
            output += f"- {os.path.basename(imp)}\n"
        if not data['imports']:
            output += "- (없음)\n"

        output += f"\n### Exports ({len(data['exports'])}개)\n"
        for exp in data['exports']:
            output += f"- {exp}\n"
        if not data['exports']:
            output += "- (없음)\n"

        output += f"\n### Dependents\n"
        output += f"**직접 ({len(direct_dependents)}개)**:\n"
        if direct_dependents:
            for dep in direct_dependents:
                output += f"- {os.path.basename(dep)}\n"
        else:
            output += "- (없음)\n"

        output += f"\n**간접 - Re-export 체인 ({len(indirect_dependents)}개)**:\n"
        if indirect_dependents:
            for dep in indirect_dependents:
                output += f"- {os.path.basename(dep)} (barrel 경로)\n"
        else:
            output += "- (없음)\n"

        output += f"\n**전체 ({total_count}개)**:\n"
        if all_dependents:
            for dep in all_dependents[:10]:
                output += f"- {os.path.basename(dep)}\n"
            if total_count > 10:
                output += f"- ... 외 {total_count - 10}개\n"
        else:
            output += "- (없음)\n"

        output += f"\n### 영향도\n"
        output += f"{risk_emoji} **{risk}** - {total_count}개 파일 의존\n"

        return [TextContent(type="text", text=output)]

    elif name == "detect_breaking_changes":
        if not ensure_dependency_graph():
            return [TextContent(type="text", text=f"의존성 그래프를 빌드할 수 없습니다.")]

        file_path = arguments.get("file_path")
        resolved_path = resolve_file_path(file_path)

        if not resolved_path:
            return [TextContent(type="text", text=f"파일을 찾을 수 없습니다: {file_path}")]

        old_exports = arguments.get("old_exports", [])
        new_exports = arguments.get("new_exports", [])

        result = detect_breaking_changes(resolved_path, old_exports, new_exports)

        output = f"## Breaking Change 분석\n\n"
        output += f"**파일**: {os.path.basename(file_path)}\n"
        output += f"**위험도**: {result['risk'].upper()}\n\n"

        if result['removed']:
            output += f"### 제거된 Exports ({len(result['removed'])}개)\n"
            for exp in result['removed']:
                output += f"- {exp}\n"

        if result['added']:
            output += f"\n### 추가된 Exports ({len(result['added'])}개)\n"
            for exp in result['added']:
                output += f"- {exp}\n"

        if result['affected_files']:
            output += f"\n### 영향받는 파일 ({len(result['affected_files'])}개)\n"
            for affected in result['affected_files'][:10]:
                output += f"- {os.path.basename(affected)}\n"
            if len(result['affected_files']) > 10:
                output += f"- ... 외 {len(result['affected_files']) - 10}개\n"
        else:
            output += f"\n영향받는 파일 없음\n"

        return [TextContent(type="text", text=output)]

    elif name == "suggest_cascade_fix":
        if not ensure_dependency_graph():
            return [TextContent(type="text", text=f"의존성 그래프를 빌드할 수 없습니다.")]

        file_path = arguments.get("file_path")
        removed_exports = arguments.get("removed_exports", [])

        resolved_path = resolve_file_path(file_path)
        if not resolved_path:
            return [TextContent(type="text", text=f"파일을 찾을 수 없습니다: {file_path}")]

        result = suggest_cascade_fix(resolved_path, removed_exports)

        output = f"## Cascade Fix 제안\n\n"

        if result['affected_files']:
            output += f"총 {len(result['affected_files'])}개 파일 수정 필요\n\n"

            for i, suggestion in enumerate(result['affected_files'], 1):
                output += f"### {i}. {os.path.basename(suggestion['file'])}\n"
                output += f"**제거 필요**: {', '.join(suggestion['imports_to_remove'])}\n"
                output += f"**제안**: {suggestion['suggestion']}\n\n"
        else:
            output += "수정 필요한 파일 없음\n"

        return [TextContent(type="text", text=output)]

    elif name == "visualize_dependencies":
        if not ensure_dependency_graph():
            return [TextContent(type="text", text=f"의존성 그래프를 빌드할 수 없습니다.")]

        file_path = arguments.get("file_path")
        depth = arguments.get("depth", 2)

        resolved_path = None
        if file_path:
            resolved_path = resolve_file_path(file_path)
            if not resolved_path:
                return [TextContent(type="text", text=f"파일을 찾을 수 없습니다: {file_path}")]

        # Mermaid 다이어그램 생성
        mermaid_lines = ["```mermaid", "graph TD"]

        if resolved_path:
            # 특정 파일 중심
            visited = set()
            edges = set()

            def add_node(fp, current_depth=0):
                if current_depth > depth or fp in visited:
                    return
                visited.add(fp)

                if fp not in config.DEPENDENCY_GRAPH:
                    return

                fp_name = os.path.basename(fp).replace('.', '_')

                # imports
                for imp in config.DEPENDENCY_GRAPH[fp]["imports"]:
                    imp_name = os.path.basename(imp).replace('.', '_')
                    edge = f"    {imp_name} --> {fp_name}"
                    if edge not in edges:
                        edges.add(edge)
                        mermaid_lines.append(edge)
                    add_node(imp, current_depth + 1)

                # dependents
                for dep in config.DEPENDENCY_GRAPH[fp]["dependents"]:
                    dep_name = os.path.basename(dep).replace('.', '_')
                    edge = f"    {fp_name} --> {dep_name}"
                    if edge not in edges:
                        edges.add(edge)
                        mermaid_lines.append(edge)
                    add_node(dep, current_depth + 1)

            add_node(resolved_path)
        else:
            # 전체 그래프 (최대 20개 노드)
            count = 0
            for fp, data in list(config.DEPENDENCY_GRAPH.items())[:20]:
                fp_name = os.path.basename(fp).replace('.', '_')
                for imp in data["imports"]:
                    imp_name = os.path.basename(imp).replace('.', '_')
                    mermaid_lines.append(f"    {imp_name} --> {fp_name}")
                    count += 1
                if count > 50:
                    break

        mermaid_lines.append("```")
        mermaid = "\n".join(mermaid_lines)

        return [TextContent(type="text", text=mermaid)]

    elif name == "find_dead_code":
        if not ensure_dependency_graph():
            return [TextContent(type="text", text=f"의존성 그래프를 빌드할 수 없습니다.")]

        dead_exports = []

        for file_path, data in config.DEPENDENCY_GRAPH.items():
            exports = data.get('exports', [])

            if not exports:
                continue

            all_dependents = calculate_all_dependents(file_path)

            if not all_dependents:
                dead_exports.append({
                    'file': file_path,
                    'exports': exports,
                    'count': len(exports)
                })

        output = "## Dead Code 감지 결과\n\n"

        if not dead_exports:
            output += "Dead code가 발견되지 않았습니다!\n"
            output += "모든 export가 최소 1개 이상의 파일에서 사용되고 있습니다.\n"
        else:
            output += f"총 {len(dead_exports)}개 파일에서 사용되지 않는 export 발견\n\n"

            for item in sorted(dead_exports, key=lambda x: x['count'], reverse=True):
                output += f"### {os.path.basename(item['file'])}\n"
                output += f"- **{item['count']}개 export**, **0개 dependent**\n"
                output += f"- Exports: {', '.join(item['exports'])}\n"
                output += f"- 경로: `{item['file']}`\n\n"

        return [TextContent(type="text", text=output)]

    elif name == "track_field_usage":
        if not ensure_dependency_graph():
            return [TextContent(type="text", text=f"의존성 그래프를 빌드할 수 없습니다.")]

        file_path = arguments.get("file_path")
        field_name = arguments.get("field_name")

        resolved_path = resolve_file_path(file_path)
        if not resolved_path:
            return [TextContent(type="text", text=f"파일을 찾을 수 없습니다: {file_path}")]

        result = track_field_usage(resolved_path, field_name)

        if "error" in result:
            return [TextContent(type="text", text=f"{result['error']}")]

        output = f"## Field Usage Tracking: `{field_name}`\n\n"
        output += f"**파일**: {os.path.basename(result['source_file'])}\n"
        output += f"**총 사용처**: {result['total_usage_count']}개 (내부: {result['internal_count']}, 외부: {result['external_count']})\n"
        output += f"**위험도**: {result['risk']}\n\n"

        output += f"### 정의 ({len(result['definitions'])}곳)\n"
        for defn in result['definitions']:
            output += f"- **Line {defn['line']}** ({defn['context']})\n"
            output += f"  ```typescript\n  {defn['code']}\n  ```\n"

        output += f"\n### 내부 사용처 ({len(result['internal_usage'])}곳)\n"
        if result['internal_usage']:
            for usage in result['internal_usage']:
                emoji = "write" if usage['usage_type'] == 'write' else "read"
                output += f"- {emoji} **Line {usage['line']}** ({usage['usage_type']})\n"
                output += f"  ```typescript\n  {usage['code']}\n  ```\n"
        else:
            output += "- (없음)\n"

        output += f"\n### 외부 사용처 ({len(result['external_usage'])}개 파일)\n"
        if result['external_usage']:
            for ext in result['external_usage']:
                file_basename = os.path.basename(ext['file'])
                output += f"\n**{file_basename}** ({len(ext['usages'])}곳):\n"
                for usage in ext['usages'][:3]:
                    output += f"  - Line {usage['line']} ({usage['usage_type']})\n"
                    output += f"    ```typescript\n    {usage['code']}\n    ```\n"
                if len(ext['usages']) > 3:
                    output += f"  - ... 외 {len(ext['usages']) - 3}곳\n"
        else:
            output += "- (없음)\n"

        return [TextContent(type="text", text=output)]

    elif name == "rename_symbol":
        if not ensure_dependency_graph():
            return [TextContent(type="text", text=f"의존성 그래프를 빌드할 수 없습니다.")]

        file_path = arguments.get("file_path")
        old_name = arguments.get("old_name")
        new_name = arguments.get("new_name")
        dry_run = arguments.get("dry_run", True)

        resolved_path = resolve_file_path(file_path)
        if not resolved_path:
            return [TextContent(type="text", text=f"파일을 찾을 수 없습니다: {file_path}")]

        result = rename_symbol(resolved_path, old_name, new_name, dry_run)

        if result.get("status") == "error":
            return [TextContent(type="text", text=f"{result['message']}")]

        output = f"## {'Preview:' if dry_run else 'Applied:'} Rename `{old_name}` -> `{new_name}`\n\n"

        if dry_run:
            output += "**IMPORTANT**: This is a PREVIEW only. No files were modified.\n\n"

        output += f"**Summary:**\n"
        output += f"- Files to change: {result['files_changed']}\n"
        output += f"- Total changes: {result['total_changes']}\n\n"

        output += "### Files that will be modified:\n\n"
        for file_change in result['changes_by_file']:
            if file_change['count'] == 0:
                continue

            file_basename = os.path.basename(file_change['file'])
            output += f"**{file_basename}** ({file_change['count']} changes):\n"

            for change in file_change['changes'][:5]:
                output += f"  - Line {change['line']}\n"
                output += f"    ```diff\n"
                output += f"    - {change['old']}\n"
                output += f"    + {change['new']}\n"
                output += f"    ```\n"

            if file_change['count'] > 5:
                output += f"  - ... and {file_change['count'] - 5} more changes\n"

            output += "\n"

        return [TextContent(type="text", text=output)]

    elif name == "detect_circular_dependencies":
        if not ensure_dependency_graph():
            return [TextContent(type="text", text=f"의존성 그래프를 빌드할 수 없습니다. 프로젝트 루트에서 실행하세요.")]

        # Tarjan's Algorithm으로 순환 의존성 감지
        cycles = detect_circular_dependencies(config.DEPENDENCY_GRAPH)

        # 포맷팅
        result = format_circular_dependencies(cycles, config.PROJECT_ROOT)

        return [TextContent(type="text", text=result)]

    elif name == "identify_entry_points":
        if not ensure_dependency_graph():
            return [TextContent(type="text", text=f"의존성 그래프를 빌드할 수 없습니다. 프로젝트 루트에서 실행하세요.")]

        top_n = arguments.get("top_n", 20)

        # Entry Point 식별
        entry_points = identify_entry_points(config.DEPENDENCY_GRAPH, config.PROJECT_ROOT)

        # 포맷팅
        result = format_entry_points(entry_points, top_n)

        return [TextContent(type="text", text=result)]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """MCP 서버 실행"""
    # 서버 시작 시 캐시 자동 로드
    load_dependency_graph_cache()

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
