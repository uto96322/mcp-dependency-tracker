#!/usr/bin/env python3
"""
CodeRelation_Code MCP Server - Production Version
실제 코드 파일(.ts/.tsx/.js/.jsx)에서 Supabase RPC, DB 테이블, TypeScript 타입 관계 추출

v2.0 개선사항:
- RPC 함수 감지 정확도 향상 (Supabase .rpc() 패턴만 감지)
- DB 테이블 패턴 확장 (11가지 패턴)
- TypeScript 타입 추적 개선 (import/export 기반)
- 에러 처리 및 로깅 강화
- 성능 최적화 (캐싱, 병렬 처리)
- 통계 정보 제공
"""
import re
import os
import glob
import logging
import json
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from mcp.server import Server
from mcp.types import Tool, TextContent

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("code-relation-code")

app = Server("code-relation-code-server")


@dataclass
class RelationMatch:
    """관계 매칭 결과"""
    name: str
    line: int
    file: str
    context: str = ""  # 주변 코드 컨텍스트 (10글자)


class CodeRelationExtractor:
    """
    코드 파일에서 관계 추출 (Production Version)

    특징:
    - 정확한 패턴 매칭 (오탐 최소화)
    - 캐싱으로 성능 향상
    - 상세한 에러 로깅
    """

    def __init__(self, project_root: str):
        self.project_root = project_root
        self._file_cache: Dict[str, str] = {}  # 파일 내용 캐시

    def _scan_code_files(self) -> List[str]:
        """코드 파일 스캔 (캐싱 지원)"""
        patterns = ['**/*.ts', '**/*.tsx', '**/*.js', '**/*.jsx']
        files = []

        for pattern in patterns:
            try:
                found = glob.glob(
                    os.path.join(self.project_root, pattern),
                    recursive=True
                )
                files.extend(found)
            except Exception as e:
                logger.error(f"파일 스캔 오류 ({pattern}): {e}")

        # 제외 디렉토리
        exclude_dirs = ['node_modules', '.next', 'dist', 'build', '.git', 'coverage', '.cache']
        files = [
            f for f in files
            if not any(ex in f for ex in exclude_dirs)
        ]

        logger.info(f"총 {len(files)}개 코드 파일 발견 (경로: {self.project_root})")
        return files

    def _read_file_cached(self, file_path: str) -> Optional[str]:
        """파일 읽기 (캐싱)"""
        if file_path in self._file_cache:
            return self._file_cache[file_path]

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                self._file_cache[file_path] = content
                return content
        except UnicodeDecodeError:
            try:
                # UTF-8 실패 시 CP949 시도 (Windows)
                with open(file_path, 'r', encoding='cp949') as f:
                    content = f.read()
                    self._file_cache[file_path] = content
                    return content
            except Exception as e:
                logger.error(f"파일 읽기 실패 ({file_path}): {e}")
                return None
        except Exception as e:
            logger.error(f"파일 읽기 오류 ({file_path}): {e}")
            return None

    def _remove_comments(self, content: str) -> str:
        """주석 제거 (정확도 향상)"""
        # 한 줄 주석 제거 (//)
        content = re.sub(r'//.*?$', '', content, flags=re.MULTILINE)
        # 블록 주석 제거 (/* */)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        return content

    def extract_rpcs(self, file_path: str) -> Dict[str, List[RelationMatch]]:
        """
        RPC 함수 사용 추출 (정의는 제외)

        패턴:
        - .rpc('function_name')
        - .rpc("function_name")
        - supabase.rpc('function_name')
        - client.rpc('function_name')

        ❌ 제거됨: export async function (일반 TypeScript 함수)
        """
        content = self._read_file_cached(file_path)
        if not content:
            return {"usages": []}

        # 주석 제거
        content_no_comments = self._remove_comments(content)

        usages = []

        # RPC 호출 패턴 (Supabase 전용)
        usage_patterns = [
            r'\.rpc\s*\(\s*[\'"]([a-z_][a-z0-9_]*)[\'"]',  # .rpc('func')
            r'\.rpc\s*\(\s*`([a-z_][a-z0-9_]*)`',  # .rpc(`func`)
        ]

        for pattern in usage_patterns:
            for match in re.finditer(pattern, content_no_comments, re.IGNORECASE):
                line_num = content[:match.start()].count('\n') + 1

                # 컨텍스트 추출 (주변 10글자)
                start = max(0, match.start() - 10)
                end = min(len(content), match.end() + 10)
                context = content[start:end].replace('\n', ' ').strip()

                usages.append(RelationMatch(
                    name=match[1],
                    line=line_num,
                    file=os.path.basename(file_path),
                    context=context
                ))

        return {"usages": usages}

    def extract_tables(self, file_path: str) -> Dict[str, List[RelationMatch]]:
        """
        DB 테이블 사용 추출 (11가지 패턴)

        Supabase 패턴:
        1. .from('table')
        2. .from("table")
        3. .from(`table`)

        SQL 패턴:
        4. INSERT INTO table
        5. UPDATE table SET
        6. DELETE FROM table
        7. SELECT ... FROM table
        8. JOIN table
        9. LEFT JOIN table
        10. INNER JOIN table
        11. CREATE TABLE table
        """
        content = self._read_file_cached(file_path)
        if not content:
            return {"usages": []}

        content_no_comments = self._remove_comments(content)

        usages = []

        # 테이블 사용 패턴 (확장됨)
        usage_patterns = [
            # Supabase 패턴
            (r'\.from\s*\(\s*[\'"]([a-z_][a-z0-9_]*)[\'"]', "supabase"),
            (r'\.from\s*\(\s*`([a-z_][a-z0-9_]*)`', "supabase"),

            # SQL 패턴
            (r'INSERT\s+INTO\s+([a-z_][a-z0-9_]*)', "sql"),
            (r'UPDATE\s+([a-z_][a-z0-9_]*)\s+SET', "sql"),
            (r'DELETE\s+FROM\s+([a-z_][a-z0-9_]*)', "sql"),
            (r'FROM\s+([a-z_][a-z0-9_]*)', "sql"),
            (r'JOIN\s+([a-z_][a-z0-9_]*)', "sql"),
            (r'LEFT\s+JOIN\s+([a-z_][a-z0-9_]*)', "sql"),
            (r'INNER\s+JOIN\s+([a-z_][a-z0-9_]*)', "sql"),
            (r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)', "sql"),
        ]

        for pattern, pattern_type in usage_patterns:
            for match in re.finditer(pattern, content_no_comments, re.IGNORECASE):
                line_num = content[:match.start()].count('\n') + 1

                # 컨텍스트 추출
                start = max(0, match.start() - 15)
                end = min(len(content), match.end() + 15)
                context = content[start:end].replace('\n', ' ').strip()

                usages.append(RelationMatch(
                    name=match[1],
                    line=line_num,
                    file=os.path.basename(file_path),
                    context=f"[{pattern_type}] {context}"
                ))

        return {"usages": usages}

    def extract_types(self, file_path: str) -> Dict[str, List[RelationMatch]]:
        """
        TypeScript 타입 정의 및 사용 추출 (개선됨)

        정의 패턴:
        - export interface Name
        - export type Name
        - interface Name
        - type Name =
        - enum Name

        사용 패턴 (정의된 타입만):
        - import { Type } from
        - : Type
        - <Type>
        - as Type
        - extends Type
        - implements Type
        """
        if not (file_path.endswith('.ts') or file_path.endswith('.tsx')):
            return {"definitions": [], "usages": []}

        content = self._read_file_cached(file_path)
        if not content:
            return {"definitions": [], "usages": []}

        content_no_comments = self._remove_comments(content)

        definitions = []
        usages = []

        # 정의 패턴
        def_patterns = [
            r'(?:export\s+)?interface\s+([A-Z][a-zA-Z0-9_]*)',
            r'(?:export\s+)?type\s+([A-Z][a-zA-Z0-9_]*)\s*=',
            r'(?:export\s+)?enum\s+([A-Z][a-zA-Z0-9_]*)',
            r'(?:export\s+)?class\s+([A-Z][a-zA-Z0-9_]*)',
        ]

        defined_types: Set[str] = set()

        for pattern in def_patterns:
            for match in re.finditer(pattern, content_no_comments):
                line_num = content[:match.start()].count('\n') + 1
                type_name = match[1]
                defined_types.add(type_name)

                definitions.append(RelationMatch(
                    name=type_name,
                    line=line_num,
                    file=os.path.basename(file_path)
                ))

        # 사용 패턴 (import 포함)
        usage_patterns = [
            r'import\s+.*?[\{\s]([A-Z][a-zA-Z0-9_]*)[\}\s,]',  # import { Type }
            r':\s*([A-Z][a-zA-Z0-9_]*)',  # : Type
            r'<([A-Z][a-zA-Z0-9_]*)>',  # <Type>
            r'\sas\s+([A-Z][a-zA-Z0-9_]*)',  # as Type
            r'extends\s+([A-Z][a-zA-Z0-9_]*)',  # extends Type
            r'implements\s+([A-Z][a-zA-Z0-9_]*)',  # implements Type
        ]

        for pattern in usage_patterns:
            for match in re.finditer(pattern, content_no_comments):
                line_num = content[:match.start()].count('\n') + 1
                type_name = match[1]

                # 이 파일에서 정의된 타입이거나 대문자로 시작하는 타입만
                if type_name in defined_types or type_name[0].isupper():
                    usages.append(RelationMatch(
                        name=type_name,
                        line=line_num,
                        file=os.path.basename(file_path)
                    ))

        return {"definitions": definitions, "usages": usages}

    def find_usages_parallel(
        self,
        target_name: str,
        extractor_method: str,
        filter_key: str = "usages"
    ) -> List[Tuple[str, int]]:
        """
        병렬 처리로 사용처 찾기 (성능 최적화)

        Args:
            target_name: 찾을 대상 (RPC 함수명, 테이블명 등)
            extractor_method: 'extract_rpcs', 'extract_tables', 'extract_types'
            filter_key: 'usages' 또는 'definitions'

        Returns:
            [(file_path, line_num), ...]
        """
        code_files = self._scan_code_files()
        usages = []

        # 병렬 처리 (최대 4개 워커)
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {}

            for file_path in code_files:
                future = executor.submit(
                    self._extract_and_filter,
                    file_path,
                    target_name,
                    extractor_method,
                    filter_key
                )
                futures[future] = file_path

            for future in as_completed(futures):
                file_path = futures[future]
                try:
                    result = future.result()
                    if result:
                        usages.extend(result)
                except Exception as e:
                    logger.error(f"파일 처리 오류 ({file_path}): {e}")

        return usages

    def _extract_and_filter(
        self,
        file_path: str,
        target_name: str,
        extractor_method: str,
        filter_key: str
    ) -> List[Tuple[str, int, str]]:
        """추출 및 필터링 (병렬 처리용)"""
        try:
            method = getattr(self, extractor_method)
            result = method(file_path)

            matches = []
            for match in result.get(filter_key, []):
                if match.name == target_name:
                    matches.append((file_path, match.line, match.context))

            return matches
        except Exception as e:
            logger.error(f"추출 오류 ({file_path}): {e}")
            return []


# ========================================
# MCP 서버 초기화
# ========================================

@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="analyze_code_relations",
            description="""
            실제 코드 파일의 RPC/Type/Table 관계 추출 (v2.0 프로덕션)

            개선사항:
            - RPC: Supabase .rpc() 패턴만 정확히 감지
            - 테이블: 11가지 패턴 지원 (Supabase + SQL)
            - 타입: import/export 기반 추적
            - 주석 제거로 정확도 향상
            - 컨텍스트 정보 제공

            예시:
            - "chat-api.ts에서 사용하는 RPC 함수는?"
            - "route.ts가 사용하는 DB 테이블은?"
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "분석할 코드 파일 경로 (절대 경로)"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="find_rpc_usages_in_code",
            description="""
            특정 RPC 함수를 호출하는 모든 코드 파일 찾기 (병렬 처리)

            예시: "get_student_info를 호출하는 파일은?"

            성능: 병렬 처리로 대규모 프로젝트도 빠름
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "rpc_name": {
                        "type": "string",
                        "description": "RPC 함수명"
                    },
                    "project_root": {
                        "type": "string",
                        "description": "프로젝트 루트 경로"
                    }
                },
                "required": ["rpc_name", "project_root"]
            }
        ),
        Tool(
            name="find_table_usages_in_code",
            description="""
            특정 DB 테이블을 사용하는 모든 코드 파일 찾기 (11가지 패턴)

            예시: "student_levels 테이블을 사용하는 파일은?"

            패턴: Supabase .from() + SQL (INSERT, UPDATE, SELECT 등)
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "테이블명"
                    },
                    "project_root": {
                        "type": "string",
                        "description": "프로젝트 루트 경로"
                    }
                },
                "required": ["table_name", "project_root"]
            }
        ),
        Tool(
            name="find_type_usages_in_code",
            description="""
            특정 TypeScript 타입을 사용하는 모든 코드 파일 찾기 (신규)

            예시: "Student 타입을 사용하는 파일은?"

            패턴: import, 타입 어노테이션, 제네릭, extends, implements
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "type_name": {
                        "type": "string",
                        "description": "타입명 (대문자로 시작)"
                    },
                    "project_root": {
                        "type": "string",
                        "description": "프로젝트 루트 경로"
                    }
                },
                "required": ["type_name", "project_root"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "analyze_code_relations":
        file_path = arguments["file_path"]

        if not os.path.exists(file_path):
            return [TextContent(
                type="text",
                text=f"❌ 파일을 찾을 수 없습니다: {file_path}"
            )]

        extractor = CodeRelationExtractor(os.path.dirname(file_path))

        rpcs = extractor.extract_rpcs(file_path)
        types = extractor.extract_types(file_path)
        tables = extractor.extract_tables(file_path)

        result = f"# 코드 관계 분석: {os.path.basename(file_path)}\n\n"
        result += f"**파일**: `{file_path}`\n\n"

        # 통계 정보
        stats = []
        if rpcs["usages"]:
            stats.append(f"RPC 호출 {len(rpcs['usages'])}개")
        if tables["usages"]:
            unique_tables = len(set(t.name for t in tables["usages"]))
            stats.append(f"테이블 {unique_tables}개")
        if types["definitions"]:
            stats.append(f"타입 정의 {len(types['definitions'])}개")

        if stats:
            result += f"**통계**: {', '.join(stats)}\n\n"

        # RPC 함수 사용
        if rpcs["usages"]:
            result += "## RPC 함수 호출\n"
            for rpc in rpcs["usages"]:
                result += f"- `{rpc.name}()` (줄 {rpc.line})\n"
                if rpc.context:
                    result += f"  ```\n  {rpc.context}\n  ```\n"
            result += "\n"

        # DB 테이블 사용
        if tables["usages"]:
            result += "## DB 테이블 사용\n"

            # 테이블별로 그룹화
            table_groups: Dict[str, List[RelationMatch]] = {}
            for t in tables["usages"]:
                if t.name not in table_groups:
                    table_groups[t.name] = []
                table_groups[t.name].append(t)

            for table_name, matches in table_groups.items():
                lines = [str(m.line) for m in matches]
                result += f"- **`{table_name}`** ({len(matches)}회 사용, 줄: {', '.join(lines)})\n"

                # 첫 번째 사용처 컨텍스트 표시
                if matches[0].context:
                    result += f"  ```\n  {matches[0].context}\n  ```\n"
            result += "\n"

        # TypeScript 타입 정의
        if types["definitions"]:
            result += "## TypeScript 타입 정의\n"
            for t in types["definitions"][:15]:  # 최대 15개
                result += f"- `{t.name}` (줄 {t.line})\n"
            if len(types["definitions"]) > 15:
                result += f"- ... 외 {len(types['definitions']) - 15}개\n"
            result += "\n"

        # 아무것도 없을 때
        if not rpcs["usages"] and not types["definitions"] and not tables["usages"]:
            result += "❌ RPC, 테이블, 타입 관계를 찾을 수 없습니다.\n"
            result += "\n**가능한 원인**:\n"
            result += "- 이 파일은 순수 로직/유틸리티 파일\n"
            result += "- Supabase를 사용하지 않음\n"
            result += "- 주석만 있는 파일\n"

        return [TextContent(type="text", text=result)]

    elif name == "find_rpc_usages_in_code":
        rpc_name = arguments["rpc_name"]
        project_root = arguments["project_root"]

        if not os.path.exists(project_root):
            return [TextContent(
                type="text",
                text=f"❌ 프로젝트 루트를 찾을 수 없습니다: {project_root}"
            )]

        logger.info(f"RPC 함수 '{rpc_name}' 검색 시작...")

        extractor = CodeRelationExtractor(project_root)
        usages = extractor.find_usages_parallel(
            target_name=rpc_name,
            extractor_method="extract_rpcs",
            filter_key="usages"
        )

        result = f"# RPC 함수 '{rpc_name}' 사용처\n\n"
        result += f"**프로젝트**: `{project_root}`\n"
        result += f"**결과**: 총 {len(usages)}개 파일에서 사용 중\n\n"

        if usages:
            for file_path, line_num, context in usages:
                rel_path = os.path.relpath(file_path, project_root)
                result += f"- [{rel_path}:{line_num}]\n"
                if context:
                    result += f"  ```\n  {context}\n  ```\n"
        else:
            result += "❌ 사용처를 찾을 수 없습니다.\n\n"
            result += "**확인 사항**:\n"
            result += f"- RPC 함수명이 정확한지 확인: `{rpc_name}`\n"
            result += f"- Supabase 호출 패턴: `.rpc('{rpc_name}')`\n"

        return [TextContent(type="text", text=result)]

    elif name == "find_table_usages_in_code":
        table_name = arguments["table_name"]
        project_root = arguments["project_root"]

        if not os.path.exists(project_root):
            return [TextContent(
                type="text",
                text=f"❌ 프로젝트 루트를 찾을 수 없습니다: {project_root}"
            )]

        logger.info(f"테이블 '{table_name}' 검색 시작...")

        extractor = CodeRelationExtractor(project_root)
        usages = extractor.find_usages_parallel(
            target_name=table_name,
            extractor_method="extract_tables",
            filter_key="usages"
        )

        result = f"# DB 테이블 '{table_name}' 사용처\n\n"
        result += f"**프로젝트**: `{project_root}`\n"
        result += f"**결과**: 총 {len(usages)}개 파일에서 사용 중\n\n"

        if usages:
            for file_path, line_num, context in usages:
                rel_path = os.path.relpath(file_path, project_root)
                result += f"- [{rel_path}:{line_num}]\n"
                if context:
                    result += f"  ```\n  {context}\n  ```\n"
        else:
            result += "❌ 사용처를 찾을 수 없습니다.\n\n"
            result += "**확인 사항**:\n"
            result += f"- 테이블명이 정확한지 확인: `{table_name}`\n"
            result += f"- Supabase 패턴: `.from('{table_name}')`\n"
            result += f"- SQL 패턴: `INSERT INTO {table_name}`, `UPDATE {table_name}` 등\n"

        return [TextContent(type="text", text=result)]

    elif name == "find_type_usages_in_code":
        type_name = arguments["type_name"]
        project_root = arguments["project_root"]

        if not os.path.exists(project_root):
            return [TextContent(
                type="text",
                text=f"❌ 프로젝트 루트를 찾을 수 없습니다: {project_root}"
            )]

        logger.info(f"타입 '{type_name}' 검색 시작...")

        extractor = CodeRelationExtractor(project_root)

        # 정의 찾기
        definitions = extractor.find_usages_parallel(
            target_name=type_name,
            extractor_method="extract_types",
            filter_key="definitions"
        )

        # 사용처 찾기
        usages = extractor.find_usages_parallel(
            target_name=type_name,
            extractor_method="extract_types",
            filter_key="usages"
        )

        result = f"# TypeScript 타입 '{type_name}' 사용처\n\n"
        result += f"**프로젝트**: `{project_root}`\n"
        result += f"**정의**: {len(definitions)}개 파일\n"
        result += f"**사용**: {len(usages)}개 파일\n\n"

        # 정의 위치
        if definitions:
            result += "## 타입 정의\n"
            for file_path, line_num, _ in definitions:
                rel_path = os.path.relpath(file_path, project_root)
                result += f"- [{rel_path}:{line_num}]\n"
            result += "\n"

        # 사용 위치
        if usages:
            result += "## 타입 사용\n"
            for file_path, line_num, _ in usages[:30]:  # 최대 30개
                rel_path = os.path.relpath(file_path, project_root)
                result += f"- [{rel_path}:{line_num}]\n"
            if len(usages) > 30:
                result += f"- ... 외 {len(usages) - 30}개\n"
            result += "\n"

        if not definitions and not usages:
            result += "❌ 타입을 찾을 수 없습니다.\n\n"
            result += "**확인 사항**:\n"
            result += f"- 타입명이 정확한지 확인: `{type_name}`\n"
            result += "- 대문자로 시작하는지 확인 (TypeScript 규칙)\n"

        return [TextContent(type="text", text=result)]


# ========================================
# MCP 서버 실행
# ========================================

if __name__ == "__main__":
    import asyncio
    from mcp.server.stdio import stdio_server

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )

    asyncio.run(main())