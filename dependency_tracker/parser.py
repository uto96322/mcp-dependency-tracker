#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AST 파싱 및 Import/Export 추출

이 모듈은 Tree-sitter를 사용하여 TypeScript/JavaScript/Python 파일의 AST를 파싱하고,
import/export 구문을 추출합니다.
"""
import sys
from pathlib import Path
from typing import Dict, List
from collections import defaultdict
from tree_sitter import Parser

from .config import (
    TS_LANGUAGE,
    TSX_LANGUAGE,
    JS_LANGUAGE,
    PY_LANGUAGE,
    USAGE_CACHE
)


def get_parser(file_ext: str) -> Parser:
    """파일 확장자에 맞는 Parser 반환"""
    parser = Parser()

    if file_ext == '.tsx':
        parser.language = TSX_LANGUAGE
    elif file_ext == '.ts':
        parser.language = TS_LANGUAGE
    elif file_ext in ['.js', '.jsx']:
        parser.language = JS_LANGUAGE
    elif file_ext == '.py':
        parser.language = PY_LANGUAGE
    else:
        raise ValueError(f"Unsupported file type: {file_ext}")

    return parser


def parse_imports(file_path: str) -> Dict[str, List[str]]:
    """
    파일의 import/export 구문 파싱

    Returns:
        {
            "imports": ["@/lib/db", "./user", "react"],
            "exports": ["getUserById", "User"],
            "named_imports": {"react": ["useState", "useEffect"]}
        }
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return {"imports": [], "exports": [], "named_imports": {}}

        content = path.read_text(encoding='utf-8')
        file_ext = path.suffix

        parser = get_parser(file_ext)
        tree = parser.parse(bytes(content, 'utf8'))
        root = tree.root_node

        imports = []
        exports = []
        named_imports = defaultdict(list)

        # TypeScript/JavaScript import 추출
        if file_ext in ['.ts', '.tsx', '.js', '.jsx']:
            for node in root.children:
                # import 문 파싱
                if node.type == 'import_statement':
                    # import { useState } from 'react'
                    source_node = node.child_by_field_name('source')
                    if source_node:
                        import_path = source_node.text.decode('utf8').strip('"\'')
                        imports.append(import_path)

                        # named imports 추출
                        for child in node.children:
                            if child.type == 'import_clause':
                                for named in child.children:
                                    if named.type == 'named_imports':
                                        for spec in named.children:
                                            if spec.type == 'import_specifier':
                                                name_node = spec.child_by_field_name('name')
                                                if name_node:
                                                    named_imports[import_path].append(
                                                        name_node.text.decode('utf8')
                                                    )

                # export 문 파싱
                elif node.type in ['export_statement', 'export_declaration']:
                    for child in node.children:
                        # export function foo() {...}
                        # export async function* foo() {...}  (generator)
                        if child.type in ['function_declaration', 'generator_function_declaration']:
                            name_node = child.child_by_field_name('name')
                            if name_node:
                                exports.append(name_node.text.decode('utf8'))
                        # export const foo = ...
                        elif child.type == 'lexical_declaration':
                            for var_decl in child.children:
                                if var_decl.type == 'variable_declarator':
                                    name_node = var_decl.child_by_field_name('name')
                                    if name_node:
                                        exports.append(name_node.text.decode('utf8'))
                        # export interface Foo {...}
                        elif child.type == 'interface_declaration':
                            # interface_declaration 구조: interface > type_identifier > interface_body
                            for iface_child in child.children:
                                if iface_child.type == 'type_identifier':
                                    exports.append(iface_child.text.decode('utf8'))
                        # export type Foo = ...
                        elif child.type == 'type_alias_declaration':
                            for type_child in child.children:
                                if type_child.type == 'type_identifier':
                                    exports.append(type_child.text.decode('utf8'))
                        # export class Foo {...}  ⭐ Bug Fix: Class export 파싱 추가
                        elif child.type == 'class_declaration':
                            name_node = child.child_by_field_name('name')
                            if name_node:
                                exports.append(name_node.text.decode('utf8'))

        # Python import/export 추출
        elif file_ext == '.py':
            for node in root.children:
                # import os
                # import sys
                if node.type == 'import_statement':
                    for child in node.children:
                        if child.type == 'dotted_name':
                            imports.append(child.text.decode('utf8'))

                # from module import function
                elif node.type == 'import_from_statement':
                    module_node = node.child_by_field_name('module_name')
                    if module_node:
                        module_name = module_node.text.decode('utf8')
                        imports.append(module_name)

                        # named imports 추출
                        for child in node.children:
                            if child.type == 'dotted_name':
                                for spec in child.children:
                                    if spec.type == 'identifier':
                                        named_imports[module_name].append(
                                            spec.text.decode('utf8')
                                        )

                # def function_name(...):
                elif node.type == 'function_definition':
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        func_name = name_node.text.decode('utf8')
                        # Private 함수 제외 (_로 시작)
                        if not func_name.startswith('_'):
                            exports.append(func_name)

                # class ClassName:
                elif node.type == 'class_definition':
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        class_name = name_node.text.decode('utf8')
                        # Private 클래스 제외
                        if not class_name.startswith('_'):
                            exports.append(class_name)

        return {
            "imports": imports,
            "exports": exports,
            "named_imports": dict(named_imports)
        }

    except Exception as e:
        print(f"[ERROR] Failed to parse {file_path}: {e}", file=sys.stderr)
        return {"imports": [], "exports": [], "named_imports": {}}


def check_identifier_usage(tree, identifier_name: str) -> bool:
    """
    AST에서 특정 식별자가 실제로 사용되는지 확인 (Phase 1 개선)

    사용으로 간주하는 경우:
    1. 함수 호출: formatDate(...)
    2. 변수 참조: const x = formatDate
    3. 객체 메서드: obj.formatDate(...)
    4. 타입 어노테이션은 제외: const x: FormatDate = ...

    Returns:
        True if identifier is actually used (not just imported)
    """
    def traverse(node):
        # Identifier 노드 찾기
        if node.type == 'identifier' and node.text.decode('utf8') == identifier_name:
            parent = node.parent

            # import/export 구문은 제외
            if parent and parent.type in ['import_specifier', 'export_specifier',
                                           'import_clause', 'named_imports']:
                return False

            # Type-only 사용은 제외 (type annotation)
            if parent and parent.type in ['type_annotation', 'type_identifier',
                                           'generic_type', 'type_arguments']:
                return False

            # import 구문 자체는 제외
            current = node
            while current:
                if current.type == 'import_statement':
                    return False
                current = current.parent

            # 실제 사용으로 간주
            return True

        # 재귀적으로 자식 노드 탐색
        for child in node.children:
            if traverse(child):
                return True

        return False

    return traverse(tree.root_node)


def get_used_imports(file_path: str, imported_names: List[str]) -> List[str]:
    """
    파일에서 실제로 사용되는 import만 필터링 (Phase 1 개선)

    Args:
        file_path: 분석할 파일 경로
        imported_names: import된 이름 목록

    Returns:
        실제로 사용되는 이름만 포함한 리스트
    """
    # 캐시 확인
    if file_path in USAGE_CACHE:
        result = []
        for name in imported_names:
            if name in USAGE_CACHE[file_path]:
                if USAGE_CACHE[file_path][name]:
                    result.append(name)
            else:
                # 캐시에 없으면 분석 필요
                break
        else:
            # 모든 이름이 캐시에 있음
            return result

    # 캐시 초기화
    if file_path not in USAGE_CACHE:
        USAGE_CACHE[file_path] = {}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 파일 확장자에 맞는 parser 선택
        path = Path(file_path)
        file_ext = path.suffix

        if file_ext == '.tsx':
            language = TSX_LANGUAGE
        elif file_ext == '.ts':
            language = TS_LANGUAGE
        elif file_ext in ['.js', '.jsx']:
            language = JS_LANGUAGE
        else:
            # 지원하지 않는 파일 타입은 안전하게 모든 import 반환
            return imported_names

        parser = Parser()
        parser.language = language
        tree = parser.parse(bytes(content, 'utf8'))

        # 실제 사용되는 import만 필터링
        used_imports = []
        for name in imported_names:
            # 캐시 확인
            if name not in USAGE_CACHE[file_path]:
                # AST 분석 (비용 높음)
                is_used = check_identifier_usage(tree, name)
                USAGE_CACHE[file_path][name] = is_used

            if USAGE_CACHE[file_path][name]:
                used_imports.append(name)

        return used_imports

    except Exception as e:
        print(f"[ERROR] Failed to check usage in {file_path}: {e}", file=sys.stderr)
        # 에러 시 안전하게 모든 import 반환 (False Negative 방지)
        return imported_names
