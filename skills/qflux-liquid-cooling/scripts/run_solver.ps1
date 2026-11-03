# TF-QFLUX 原生 Windows 启动器。适用于本机或 SSH 目标机，不保存凭据。
param(
    [string]$CaseRoot = $PSScriptRoot,
    [ValidateSet('run','run_stable','run_robust')][string]$Stage = 'run',
    [string]$InitialData = ''
)
$ErrorActionPreference = 'Stop'
$caseDirectory = (Resolve-Path -LiteralPath $CaseRoot).Path
$configuration = Get-Content -LiteralPath (Join-Path $caseDirectory 'workflow.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$qfluxDirectory = if ($env:QFLUX_HOME) { $env:QFLUX_HOME } else { $configuration.software.qflux_home }
$pythonExecutable = $configuration.software.qflux_python
$solverExecutable = Join-Path $qfluxDirectory 'QSolver.exe'
if (-not (Test-Path -LiteralPath $solverExecutable)) { throw 'QSolver.exe 不存在' }
if (-not (Test-Path -LiteralPath $pythonExecutable)) { throw '请配置匹配 ABI 的 qflux_python' }
$outputDirectory = Join-Path $caseDirectory $Stage
# 拒绝重复运行；同阶段已有输出时保留所有文件，交给操作者检查。
if (Test-Path -LiteralPath $outputDirectory) { throw '阶段目录已存在；请先检查已有任务和结果，禁止覆盖启动' }
$active = Get-CimInstance Win32_Process -Filter "Name='QSolver.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($caseDirectory) }
if ($active) { throw '本案例存在求解进程，禁止重复启动' }
$cases = @{run='parallel_cooling.qfx';run_stable='parallel_cooling_stable.qfx';run_robust='parallel_cooling_robust.qfx'}
$caseFile = Join-Path $caseDirectory $cases[$Stage]
if (-not (Test-Path -LiteralPath $caseFile)) { throw '请先创建本阶段 QFX 工程并独立回读' }
if ($InitialData) {
    $InitialData = (Resolve-Path -LiteralPath $InitialData).Path
    if ([IO.Path]::GetExtension($InitialData) -ne '.dat') { throw '续算输入必须是已确认写完的 DAT' }
} elseif ($Stage -ne 'run') { throw '续算阶段必须指定完整的 InitialData' }
New-Item -ItemType Directory -Path $outputDirectory | Out-Null
$cores = [int]$configuration.solver.mpi_cores
if ($cores -lt 1) { throw 'MPI 核数必须大于0' }
# Start-Process 的 ArgumentList 是字符串，显式引号保证带空格路径正确。
$arguments = '-q "{0}" -o "{1}" -n {2}' -f $caseFile,$outputDirectory,$cores
if ($InitialData) { $arguments += ' -i "{0}"' -f $InitialData }
try {
    $solverProcess = Start-Process -FilePath $solverExecutable -ArgumentList $arguments -WorkingDirectory $qfluxDirectory -WindowStyle Hidden -RedirectStandardOutput (Join-Path $outputDirectory 'solver_stdout.log') -RedirectStandardError (Join-Path $outputDirectory 'solver_stderr.log') -PassThru
    @{host=$env:COMPUTERNAME;pid=$solverProcess.Id;case=$caseFile;stage=$Stage;initial=$InitialData;started=(Get-Date).ToString('o');cores=$cores} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $outputDirectory 'job.json') -Encoding UTF8
    $null=$solverProcess.Handle
    $solverProcess.WaitForExit()
    @{exitCode=$solverProcess.ExitCode;finished=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $outputDirectory 'finished.json') -Encoding UTF8
    if ($solverProcess.ExitCode -ne 0) { throw ('求解器退出码：'+$solverProcess.ExitCode) }
} catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $outputDirectory 'launcher_error.log') -Encoding UTF8
    throw
}
