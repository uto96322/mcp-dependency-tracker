# mcp-dependency-tracker

MCP (Model Context Protocol) servers for TypeScript/JavaScript code intelligence.

Similar concept to Microsoft's [RPG-Encoder](https://github.com/microsoft/RPG-ZeroRepo) (incremental dependency graph, breaking change detection).

## What's Inside

### 1. dependency_tracker/
Full-featured dependency graph analyzer:
- **Incremental builds** (mtime-based, only re-parse changed files)
- **Breaking change detection** (warns before you break dependents)
- **Cascade fix suggestions**
- **Circular dependency detection**
- **Dead code finder**
- **Mermaid diagram visualization**
- **Rename refactoring support**

### 2. code_relation_code_server.py
Code relation extractor for Supabase projects:
- RPC function usage tracking
- DB table usage tracking (11 patterns)
- TypeScript type definition/usage tracking
- Parallel processing with caching

## Installation

### Prerequisites
```bash
pip install tree-sitter tree-sitter-python tree-sitter-typescript tree-sitter-javascript mcp
```

### Add to Claude Code

**Option 1: CLI**
```bash
claude mcp add dependencyTracker -s project -- python -m dependency_tracker.server
claude mcp add codeRelationCode -s project -- python /path/to/code_relation_code_server.py
```

**Option 2: `.mcp.json`**
```json
{
  "mcpServers": {
    "dependencyTracker": {
      "command": "python",
      "args": ["-m", "dependency_tracker.server"],
      "cwd": "/path/to/mcp-dependency-tracker",
      "env": { "PYTHONIOENCODING": "utf-8" }
    },
    "codeRelationCode": {
      "command": "python",
      "args": ["/path/to/code_relation_code_server.py"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

## Usage

### dependencyTracker

**When to use:**
- Before editing files (50+ lines)
- Before deleting functions/types
- Before refactoring

**Tools:**
| Tool | Description |
|:---|:---|
| `check_file_dependencies` | Check imports, exports, and dependents |
| `detect_breaking_changes` | Detect breaking changes before removing exports |
| `suggest_cascade_fix` | Get fix suggestions for breaking changes |
| `find_dead_code` | Find unused exports |
| `detect_circular_dependencies` | Detect circular imports |
| `visualize_dependencies` | Generate Mermaid diagram |

**Example:**
```
> check_file_dependencies("src/stores/user-store.ts")

Imports: auth.ts, supabase.ts
Exports: useUserStore
Dependents: chat-api.ts, profile.tsx (2 files)
Impact: LOW
```

### codeRelationCode

**When to use:**
- Before changing DB schema
- Before modifying RPC functions
- Before changing TypeScript types

**Tools:**
| Tool | Description |
|:---|:---|
| `analyze_code_relations` | Analyze RPC/Table/Type relations in a file |
| `find_rpc_usages_in_code` | Find all files calling a specific RPC |
| `find_table_usages_in_code` | Find all files using a specific table |
| `find_type_usages_in_code` | Find all files using a specific type |

**Example:**
```
> analyze_code_relations("app/api/login/route.ts")

DB Tables: student_activity_log (line 20)
RPC Functions: (none)
Types: (none)
```

## Status

⚠️ **As-is, no maintenance.**

This was built for personal use with Claude Code. Use at your own risk.

## License

MIT
