<#
.SYNOPSIS
    Windows mirror of the Makefile. `make` is not installed on the machine this was built on
    (BLOCKERS.md B-002), so this script provides the same targets by the same names.

.EXAMPLE
    ./make.ps1 test
    ./make.ps1 serve
    ./make.ps1 dogfood
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'install', 'dev', 'serve', 'build', 'test', 'test-backend',
        'test-frontend', 'lint', 'typecheck', 'eval', 'import', 'dogfood', 'export',
        'stats', 'clean', 'up', 'down')]
    [string]$Target = 'help',

    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Invoke-Step {
    param([string]$Label, [scriptblock]$Body)
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Label (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

switch ($Target) {
    'help' {
        @'
Trace2Evals - ./make.ps1 <target>

  install        install python + node dependencies (the only step needing network)
  build          build the SPA into the python package
  dev            backend (uvicorn, reload) + frontend (vite) in separate windows
  serve          build the UI, then serve everything from one process
  lint           ruff
  typecheck      strict tsc over the frontend
  test-backend   pytest
  test-frontend  vitest component tests
  test           lint + backend + typecheck + frontend
  eval           the evals/ gate: the exported suite must be well-formed and non-vacuous
  import         import the bundled synthetic fixtures
  dogfood        import + label + build cases + export v1 into evals/
  export         export the v1 suite into exports/
  stats          label distribution + case counts
  up / down      docker compose (optional)
  clean          remove the local database, build output and caches
'@ | Write-Host
    }

    'install' {
        Invoke-Step 'uv sync' { uv sync --extra dev }
        Invoke-Step 'npm install' { npm --prefix frontend install }
    }

    'build' { Invoke-Step 'vite build' { npm --prefix frontend run build } }

    'dev' {
        # Two windows rather than backgrounded jobs: reload output stays readable, and Ctrl+C in
        # either window does the obvious thing.
        Write-Host "API  -> http://127.0.0.1:$Port/api/docs" -ForegroundColor Green
        Write-Host 'UI   -> http://localhost:5173  (proxies /api to the backend)' -ForegroundColor Green
        Start-Process powershell -ArgumentList @(
            '-NoExit', '-Command',
            "Set-Location '$PSScriptRoot'; uv run uvicorn --factory t2e.api.app:create_app --reload --port $Port"
        )
        npm --prefix frontend run dev
    }

    'serve' {
        Invoke-Step 'vite build' { npm --prefix frontend run build }
        uv run t2e label --serve --port $Port
    }

    'lint' { Invoke-Step 'ruff' { uv run ruff check . } }
    'typecheck' { Invoke-Step 'tsc' { npm --prefix frontend run typecheck } }
    'test-backend' { Invoke-Step 'pytest' { uv run pytest } }
    'test-frontend' { Invoke-Step 'vitest' { npm --prefix frontend run test } }

    'test' {
        Invoke-Step 'ruff' { uv run ruff check . }
        Invoke-Step 'pytest' { uv run pytest }
        Invoke-Step 'tsc' { npm --prefix frontend run typecheck }
        Invoke-Step 'vitest' { npm --prefix frontend run test }
        Write-Host 'all green' -ForegroundColor Green
    }

    'eval' { Invoke-Step 'evals gate' { uv run pytest evals/ -p no:cacheprovider } }
    'import' { Invoke-Step 't2e import' { uv run t2e import fixtures/otel fixtures/langsmith } }
    'dogfood' { Invoke-Step 'dogfood' { uv run python scripts/dogfood.py } }

    'export' {
        Invoke-Step 't2e export' {
            uv run t2e export --version v1 --format jsonl,pytest,promptfoo --out exports
        }
    }

    'stats' { uv run t2e stats }

    'up' {
        Invoke-Step 'vite build' { npm --prefix frontend run build }
        docker compose up --build
    }
    'down' { docker compose down -v }

    'clean' {
        foreach ($path in @('.t2e', 'exports', 'backend/src/t2e/web', '.pytest_cache',
                '.ruff_cache', 'frontend/dist')) {
            if (Test-Path $path) { Remove-Item -Recurse -Force $path; Write-Host "removed $path" }
        }
        Get-ChildItem -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue |
            ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
        Write-Host 'clean' -ForegroundColor Green
    }
}
