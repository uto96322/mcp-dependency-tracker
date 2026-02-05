#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
필드 정의 추출 및 사용처 추적 (Phase 2 핵심 기능)

이 모듈은 TypeScript/JavaScript의 interface, type, class property 필드를
추적하고, 모든 사용처를 찾습니다. 필드 이름 변경 전 영향도 분석에 사용됩니다.
"""
import sys
from pathlib import Path
from typing import Dict, List

from . import config
from .parser import get_parser
from .dependency_graph import calculate_all_dependents


def extract_field_definitions(file_path: str) -> Dict[str, List[Dict]]:
    """
    파일에서 필드 정의 추출 (interface, type, class property)

    Returns:
        {
            "interface": [
                {"name": "studentName", "line": 8, "context": "interface StudentState"}
            ],
            "type": [...],
            "property": [...]
        }
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return {"interface": [], "type": [], "property": []}

        content = path.read_text(encoding='utf-8')
        file_ext = path.suffix

        if file_ext not in ['.ts', '.tsx', '.js', '.jsx']:
            return {"interface": [], "type": [], "property": []}

        parser = get_parser(file_ext)
        tree = parser.parse(bytes(content, 'utf8'))
        root = tree.root_node

        fields = {
            "interface": [],
            "type": [],
            "property": []
        }

        lines = content.split('\n')

        def get_line_number(node):
            """노드의 라인 번호 (1-based)"""
            return node.start_point[0] + 1

        def traverse_for_fields(node, parent_name=None):
            """재귀적으로 필드 정의 찾기"""

            # Interface 정의
            if node.type == 'interface_declaration':
                interface_name = None
                for child in node.children:
                    if child.type == 'type_identifier':
                        interface_name = child.text.decode('utf8')
                        break

                # Interface body에서 property 추출
                for child in node.children:
                    if child.type == 'object_type':
                        for prop in child.children:
                            if prop.type == 'property_signature':
                                for prop_child in prop.children:
                                    if prop_child.type == 'property_identifier':
                                        field_name = prop_child.text.decode('utf8')
                                        line_num = get_line_number(prop_child)
                                        fields["interface"].append({
                                            "name": field_name,
                                            "line": line_num,
                                            "context": f"interface {interface_name}",
                                            "code": lines[line_num - 1].strip() if line_num <= len(lines) else ""
                                        })

            # Type alias 정의
            elif node.type == 'type_alias_declaration':
                type_name = None
                for child in node.children:
                    if child.type == 'type_identifier':
                        type_name = child.text.decode('utf8')
                        break

                # Object type에서 property 추출
                for child in node.children:
                    if child.type == 'object_type':
                        for prop in child.children:
                            if prop.type == 'property_signature':
                                for prop_child in prop.children:
                                    if prop_child.type == 'property_identifier':
                                        field_name = prop_child.text.decode('utf8')
                                        line_num = get_line_number(prop_child)
                                        fields["type"].append({
                                            "name": field_name,
                                            "line": line_num,
                                            "context": f"type {type_name}",
                                            "code": lines[line_num - 1].strip() if line_num <= len(lines) else ""
                                        })

            # Object literal property (Zustand store 등)
            elif node.type == 'pair':
                key_node = node.child_by_field_name('key')
                if key_node and key_node.type == 'property_identifier':
                    field_name = key_node.text.decode('utf8')
                    line_num = get_line_number(key_node)
                    fields["property"].append({
                        "name": field_name,
                        "line": line_num,
                        "context": parent_name or "object",
                        "code": lines[line_num - 1].strip() if line_num <= len(lines) else ""
                    })

            # 재귀적으로 자식 노드 탐색
            for child in node.children:
                traverse_for_fields(child, parent_name)

        traverse_for_fields(root)
        return fields

    except Exception as e:
        print(f"[ERROR] Failed to extract fields from {file_path}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {"interface": [], "type": [], "property": []}


def find_field_usage_in_file(file_path: str, field_name: str) -> List[Dict]:
    """
    파일 내부에서 특정 필드의 모든 사용처 찾기

    Returns:
        [
            {"line": 39, "code": "studentName: name,", "usage_type": "write"},
            {"line": 133, "code": "{studentName || '-'}", "usage_type": "read"}
        ]
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return []

        content = path.read_text(encoding='utf-8')
        file_ext = path.suffix

        if file_ext not in ['.ts', '.tsx', '.js', '.jsx']:
            return []

        parser = get_parser(file_ext)
        tree = parser.parse(bytes(content, 'utf8'))
        root = tree.root_node

        lines = content.split('\n')
        usages = []

        def get_line_number(node):
            return node.start_point[0] + 1

        def is_definition_context(node):
            """정의 컨텍스트인지 확인 (interface, type)"""
            current = node
            while current:
                if current.type in ['interface_declaration', 'type_alias_declaration',
                                   'property_signature']:
                    return True
                current = current.parent
            return False

        def is_usage_context(node):
            """
            실제 사용 컨텍스트인지 확인 (정의/선언은 제외)

            제외할 컨텍스트:
            - 변수 선언의 이름 (const studentName = ...)
            - 함수 매개변수 (function foo(studentName) {})
            - Import 문 (import { studentName } from ...)
            - Property 정의 (interface { studentName: string })
            """
            current = node.parent

            # Import 문 제외
            while current:
                if current.type in ['import_statement', 'import_specifier', 'import_clause']:
                    return False
                current = current.parent

            # 변수 선언의 이름 제외 (const [name] = ...)
            parent = node.parent
            if parent:
                # Variable declarator의 name 부분 (const studentName = ...)
                if parent.type == 'variable_declarator':
                    # name 필드인지 확인
                    if node == parent.child_by_field_name('name'):
                        return False

                # Function parameter
                if parent.type in ['required_parameter', 'optional_parameter']:
                    return False

                # Object pattern에서 key 부분 (const { studentName } = ...)은 사용으로 간주
                if parent.type == 'shorthand_property_identifier_pattern':
                    return True

            return True

        def traverse_for_usage(node):
            """재귀적으로 필드 사용처 찾기 (모든 identifier 검사)"""

            node_text = node.text.decode('utf8') if node.text else ""

            # 🔍 모든 identifier 관련 노드 타입 검사
            if node_text == field_name:
                # 정의 컨텍스트 제외 (interface, type)
                if is_definition_context(node):
                    for child in node.children:
                        traverse_for_usage(child)
                    return

                # 사용 컨텍스트 확인
                if not is_usage_context(node):
                    for child in node.children:
                        traverse_for_usage(child)
                    return

                line_num = get_line_number(node)
                code_line = lines[line_num - 1].strip() if line_num <= len(lines) else ""

                # 사용 타입 판별
                parent = node.parent
                usage_type = "read"

                if node.type == 'property_identifier':
                    # Object property: { key: studentName } or { studentName: value }
                    if parent and parent.type == 'pair':
                        # key 위치인지 value 위치인지 확인
                        key_node = parent.child_by_field_name('key')
                        if node == key_node:
                            usage_type = "property_key"
                        else:
                            usage_type = "property_value"
                    else:
                        usage_type = "read"

                elif node.type == 'shorthand_property_identifier':
                    # { studentName } - shorthand
                    usage_type = "shorthand"

                elif node.type == 'identifier':
                    # 일반 identifier 사용
                    if parent:
                        # Member access: obj.studentName
                        if parent.type == 'member_expression':
                            property_node = parent.child_by_field_name('property')
                            if node == property_node:
                                usage_type = "member_access"
                            else:
                                usage_type = "read"

                        # Template substitution: `${studentName}`
                        elif parent.type == 'template_substitution':
                            usage_type = "template"

                        # Binary/unary expression: !studentName, studentName || other
                        elif parent.type in ['binary_expression', 'unary_expression']:
                            usage_type = "expression"

                        # Function call: func(studentName)
                        elif parent.type == 'arguments':
                            usage_type = "argument"

                        # Assignment: studentName = value
                        elif parent.type == 'assignment_expression':
                            left = parent.child_by_field_name('left')
                            if node == left:
                                usage_type = "write"
                            else:
                                usage_type = "read"

                        # Pair value: { name: studentName }
                        elif parent.type == 'pair':
                            key_node = parent.child_by_field_name('key')
                            if node != key_node:
                                usage_type = "object_value"
                            else:
                                usage_type = "read"

                        else:
                            usage_type = "read"

                usages.append({
                    "line": line_num,
                    "code": code_line,
                    "usage_type": usage_type,
                    "node_type": node.type
                })

            # 재귀적으로 자식 노드 탐색
            for child in node.children:
                traverse_for_usage(child)

        traverse_for_usage(root)

        # 라인 번호로 정렬 및 중복 제거
        unique_usages = []
        seen_lines = set()
        for usage in sorted(usages, key=lambda x: x["line"]):
            if usage["line"] not in seen_lines:
                seen_lines.add(usage["line"])
                unique_usages.append(usage)

        return unique_usages

    except Exception as e:
        print(f"[ERROR] Failed to find field usage in {file_path}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return []


def track_field_usage(file_path: str, field_name: str) -> Dict:
    """
    필드의 전체 사용처 추적 (Phase 2 핵심 기능)

    Returns:
        {
            "field_name": "studentName",
            "source_file": "src/stores/student-store.ts",
            "definitions": [
                {"line": 8, "context": "interface StudentState", "code": "studentName: string"}
            ],
            "internal_usage": [
                {"line": 29, "code": "studentName: null,", "usage_type": "write"},
                {"line": 39, "code": "studentName: name,", "usage_type": "write"}
            ],
            "external_usage": [
                {
                    "file": "src/components/LearnHeader.tsx",
                    "usages": [
                        {"line": 29, "code": "const { studentName } = useStudentStore()", "usage_type": "destructure"}
                    ]
                }
            ],
            "total_usage_count": 6,
            "risk": "HIGH"
        }
    """
    if not config.DEPENDENCY_GRAPH:
        print("[WARN] Dependency graph not built. Call build_dependency_graph first.", file=sys.stderr)
        return {
            "error": "Dependency graph not built. Call build_dependency_graph first."
        }

    # 1. 필드 정의 찾기
    field_defs = extract_field_definitions(file_path)
    all_definitions = field_defs["interface"] + field_defs["type"] + field_defs["property"]
    matching_defs = [d for d in all_definitions if d["name"] == field_name]

    if not matching_defs:
        return {
            "error": f"Field '{field_name}' not found in {file_path}",
            "searched_in": file_path
        }

    # 2. 내부 사용처 찾기 (같은 파일)
    internal_usage = find_field_usage_in_file(file_path, field_name)

    # 3. 외부 사용처 찾기 (dependent 파일들)
    external_usage = []

    if file_path in config.DEPENDENCY_GRAPH:
        all_dependents = calculate_all_dependents(file_path)

        for dependent_file in all_dependents:
            usages_in_file = find_field_usage_in_file(dependent_file, field_name)

            if usages_in_file:
                external_usage.append({
                    "file": dependent_file,
                    "usages": usages_in_file
                })

    # 4. 통계 계산
    total_internal = len(internal_usage)
    total_external = sum(len(ext["usages"]) for ext in external_usage)
    total_usage_count = total_internal + total_external

    # 5. 위험도 평가
    if total_usage_count >= 10:
        risk = "HIGH"
    elif total_usage_count >= 5:
        risk = "MEDIUM"
    else:
        risk = "LOW"

    return {
        "field_name": field_name,
        "source_file": file_path,
        "definitions": matching_defs,
        "internal_usage": internal_usage,
        "external_usage": external_usage,
        "total_usage_count": total_usage_count,
        "internal_count": total_internal,
        "external_count": total_external,
        "risk": risk
    }
