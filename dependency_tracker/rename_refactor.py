#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
심볼 이름 변경 - VSCode F2 스타일 (Phase 3 핵심 기능)

이 모듈은 TypeScript/JavaScript의 심볼(변수, 함수, 필드 등)을 프로젝트 전체에서
자동으로 이름 변경합니다. Dry-run 모드로 미리보기도 지원합니다.
"""
import sys
from pathlib import Path
from typing import Dict

from . import config
from .parser import get_parser
from .dependency_graph import calculate_all_dependents


def rename_symbol_in_file(file_path: str, old_name: str, new_name: str) -> Dict:
    """
    파일 내에서 심볼 이름 변경 (dry-run 또는 실제 적용)

    Returns:
        {
            "file": "student-store.ts",
            "changes": [
                {"line": 8, "old": "studentName: string", "new": "userName: string"},
                {"line": 29, "old": "studentName: null", "new": "userName: null"}
            ],
            "count": 2
        }
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return {"file": file_path, "changes": [], "count": 0, "error": "File not found"}

        content = path.read_text(encoding='utf-8')
        file_ext = path.suffix

        if file_ext not in ['.ts', '.tsx', '.js', '.jsx']:
            return {"file": file_path, "changes": [], "count": 0, "error": "Unsupported file type"}

        lines = content.split('\n')
        parser = get_parser(file_ext)
        tree = parser.parse(bytes(content, 'utf8'))
        root = tree.root_node

        changes = []

        def get_line_number(node):
            return node.start_point[0] + 1

        def get_column(node):
            return node.start_point[1]

        def traverse_for_rename(node):
            """재귀적으로 심볼을 찾아서 변경 위치 기록"""

            # Property identifier
            if node.type == 'property_identifier' and node.text.decode('utf8') == old_name:
                line_num = get_line_number(node)
                col = get_column(node)
                old_line = lines[line_num - 1]
                new_line = old_line[:col] + new_name + old_line[col + len(old_name):]

                changes.append({
                    "line": line_num,
                    "column": col,
                    "old": old_line.strip(),
                    "new": new_line.strip()
                })

            # Shorthand property identifier
            elif node.type == 'shorthand_property_identifier' and node.text.decode('utf8') == old_name:
                line_num = get_line_number(node)
                col = get_column(node)
                old_line = lines[line_num - 1]
                new_line = old_line[:col] + new_name + old_line[col + len(old_name):]

                changes.append({
                    "line": line_num,
                    "column": col,
                    "old": old_line.strip(),
                    "new": new_line.strip()
                })

            # Member expression property
            elif node.type == 'member_expression':
                property_node = node.child_by_field_name('property')
                if property_node and property_node.text.decode('utf8') == old_name:
                    line_num = get_line_number(property_node)
                    col = get_column(property_node)
                    old_line = lines[line_num - 1]
                    new_line = old_line[:col] + new_name + old_line[col + len(old_name):]

                    changes.append({
                        "line": line_num,
                        "column": col,
                        "old": old_line.strip(),
                        "new": new_line.strip()
                    })

            # 재귀적으로 자식 노드 탐색
            for child in node.children:
                traverse_for_rename(child)

        traverse_for_rename(root)

        # 중복 제거 (같은 라인의 중복 변경)
        unique_changes = []
        seen_lines = set()
        for change in sorted(changes, key=lambda x: (x["line"], x["column"])):
            key = (change["line"], change["column"])
            if key not in seen_lines:
                seen_lines.add(key)
                unique_changes.append(change)

        return {
            "file": file_path,
            "changes": unique_changes,
            "count": len(unique_changes)
        }

    except Exception as e:
        print(f"[ERROR] Failed to rename in {file_path}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {"file": file_path, "changes": [], "count": 0, "error": str(e)}


def rename_symbol(file_path: str, old_name: str, new_name: str, dry_run: bool = True) -> Dict:
    """
    심볼의 모든 참조를 자동으로 이름 변경 (Phase 3 핵심 기능)

    Args:
        file_path: 심볼이 정의된 파일 경로
        old_name: 기존 이름
        new_name: 새로운 이름
        dry_run: True면 미리보기만, False면 실제 파일 수정

    Returns:
        {
            "old_name": "studentName",
            "new_name": "userName",
            "source_file": "student-store.ts",
            "dry_run": True,
            "files_changed": 5,
            "total_changes": 12,
            "changes_by_file": [
                {
                    "file": "student-store.ts",
                    "count": 6,
                    "changes": [...]
                },
                {
                    "file": "chat-api.ts",
                    "count": 3,
                    "changes": [...]
                }
            ],
            "status": "success" | "error",
            "message": "..."
        }
    """
    if not config.DEPENDENCY_GRAPH:
        return {
            "status": "error",
            "message": "Dependency graph not built. Call build_dependency_graph first."
        }

    # 1. 내부 파일 변경
    source_change = rename_symbol_in_file(file_path, old_name, new_name)

    changes_by_file = [source_change]

    # 2. 외부 파일 변경 (dependent 파일들)
    if file_path in config.DEPENDENCY_GRAPH:
        all_dependents = calculate_all_dependents(file_path)

        for dependent_file in all_dependents:
            dep_change = rename_symbol_in_file(dependent_file, old_name, new_name)

            # 변경 사항이 있는 파일만 추가
            if dep_change["count"] > 0:
                changes_by_file.append(dep_change)

    # 3. 통계 계산
    files_changed = len([c for c in changes_by_file if c["count"] > 0])
    total_changes = sum(c["count"] for c in changes_by_file)

    # 4. 실제 파일 수정 (dry_run=False인 경우)
    if not dry_run and total_changes > 0:
        for file_changes in changes_by_file:
            if file_changes["count"] == 0:
                continue

            try:
                file_path_to_update = file_changes["file"]
                content = Path(file_path_to_update).read_text(encoding='utf-8')
                lines = content.split('\n')

                # 변경을 역순으로 적용 (라인 번호가 바뀌지 않도록)
                for change in sorted(file_changes["changes"], key=lambda x: (x["line"], x["column"]), reverse=True):
                    line_idx = change["line"] - 1
                    col = change["column"]
                    old_line = lines[line_idx]
                    new_line = old_line[:col] + new_name + old_line[col + len(old_name):]
                    lines[line_idx] = new_line

                # 파일 저장
                new_content = '\n'.join(lines)
                Path(file_path_to_update).write_text(new_content, encoding='utf-8')

                print(f"[INFO] Updated {file_path_to_update}: {file_changes['count']} changes", file=sys.stderr)

            except Exception as e:
                print(f"[ERROR] Failed to update {file_path_to_update}: {e}", file=sys.stderr)
                return {
                    "status": "error",
                    "message": f"Failed to update {file_path_to_update}: {e}"
                }

    return {
        "old_name": old_name,
        "new_name": new_name,
        "source_file": file_path,
        "dry_run": dry_run,
        "files_changed": files_changed,
        "total_changes": total_changes,
        "changes_by_file": changes_by_file,
        "status": "success",
        "message": f"{'Preview:' if dry_run else 'Applied:'} {total_changes} changes in {files_changed} files"
    }
