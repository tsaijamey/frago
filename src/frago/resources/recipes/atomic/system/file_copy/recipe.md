---
name: file_copy
type: atomic
runtime: shell
version: "1.0.0"
description: Copy file from source path to destination path
use_cases:
  - Backup configuration files to specified location
  - Copy intermediate result files in workflows
  - Atomic step for batch file operations
tags:
  - file
  - system
  - copy
output_targets:
  - stdout
  - file
inputs:
  source_path:
    type: string
    required: true
    description: Source file path
  dest_path:
    type: string
    required: true
    description: Destination file path
outputs:
  source:
    type: string
    description: Source file path
  destination:
    type: string
    description: Destination file path
  size_bytes:
    type: number
    description: File size (bytes)
  operation:
    type: string
    description: Type of operation performed
---

# Recipe: Copy File

## Description

Copy a file from source path to destination path and return operation result information (including file size).

## Usage

```bash
# Via command line parameters
uv run frago recipe run file_copy --params '{"source_path": "/path/to/source.txt", "dest_path": "/path/to/dest.txt"}'

# Via parameter file
echo '{"source_path": "/path/to/source.txt", "dest_path": "/path/to/dest.txt"}' > params.json
uv run frago recipe run file_copy --params-file params.json

# Output to file
uv run frago recipe run file_copy --params '{"source_path": "a.txt", "dest_path": "b.txt"}' --output-file result.json
```

## Prerequisites

- Source file must exist and be readable
- Parent directory of destination path must exist and be writable
- Requires Bash shell environment (Linux, macOS, WSL)

## Expected Output

```json
{
  "success": true,
  "data": {
    "source": "/path/to/source.txt",
    "destination": "/path/to/dest.txt",
    "size_bytes": 1024,
    "operation": "copy"
  }
}
```

## Notes

- If destination file already exists, it will be overwritten
- Copy operation does not preserve file permissions and metadata (uses standard `cp` command)
- Only supports single file copying, does not support directories

## Update History

- **v1.0.0** (2025-11-21): Initial version, supports basic file copying functionality
