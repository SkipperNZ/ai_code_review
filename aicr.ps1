param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$env:PYTHONUTF8 = '1'
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m aicr @Arguments
exit $LASTEXITCODE
