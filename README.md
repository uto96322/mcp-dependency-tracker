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

## Status

⚠️ **As-is, no maintenance.**

This was built for personal use with Claude Code. Use at your own risk.

## License

MIT
