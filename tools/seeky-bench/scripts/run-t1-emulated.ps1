<#
.SYNOPSIS
Launch `seeky-bench perf` under the H3-approved T1-emulated hardware profile on Windows.

.DESCRIPTION
Enforces the T1-emulated profile approved under Gate H3 (2026-11-27):
  - Logical CPUs 0-7 (8 CPUs) via Win32 Job Object affinity (inherited by child probes)
  - 12 GiB process memory cap (12,884,901,888 bytes) via Win32 Job Object
  - Windows High Performance power scheme during the timed run (restored on exit)
  - No Python/Cargo/Node parent process, so `seeky-bench perf`'s quiet-window check
    passes when no other heavy process is running on the workstation.

.EXAMPLE
.\tools\seeky-bench\scripts\run-t1-emulated.ps1 `
  -BenchExe .\target\release\seeky-bench.exe `
  -Corpus sdc-s `
  -Config tools\seeky-bench\configs\b0-poc-cpu.json `
  -DataDir D:\seeky-bench-data\b0-sdc-s `
  -Output docs\benchmarks\results\2026-11-27-baseline-b0\perf-cpu `
  -QueriesFile bench\qrels\sdc\drafts\sdc-v1\queries.draft.jsonl
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BenchExe,

    [Parameter(Mandatory = $true)]
    [string]$Corpus,

    [Parameter(Mandatory = $true)]
    [string]$Config,

    [Parameter(Mandatory = $true)]
    [string]$DataDir,

    [Parameter(Mandatory = $true)]
    [string]$Output,

    [string]$QueriesFile = "",
    [string]$Suite = "all",
    [string]$Stage = "single",
    [int]$Repetitions = 30,
    [int]$Queries = 0,
    [string]$Cpus = "0-7",
    [UInt64]$MemoryLimitBytes = 12884901888,
    [string]$WorkPackage = "WP-1.7",
    [string]$Spec = "SPEC-0003",
    [switch]$CodeEnabled,
    [switch]$SkipPowerPlan,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Parse-CpuMask {
    param([Parameter(Mandatory = $true)][string]$Spec)
    [UInt64]$mask = 0
    foreach ($part in $Spec.Split(",")) {
        $trimmed = $part.Trim()
        if ($trimmed -eq "") {
            throw "Empty CPU entry in '$Spec'"
        }
        if ($trimmed.Contains("-")) {
            $bounds = $trimmed.Split("-")
            if ($bounds.Count -ne 2) { throw "Invalid CPU range '$trimmed'" }
            $start = [int]$bounds[0]
            $end = [int]$bounds[1]
            if ($start -lt 0 -or $end -lt $start -or $end -ge 64) {
                throw "CPU range '$trimmed' must be within 0..63"
            }
            for ($cpu = $start; $cpu -le $end; $cpu++) {
                $mask = $mask -bor ([UInt64]1 -shl $cpu)
            }
        } else {
            $cpu = [int]$trimmed
            if ($cpu -lt 0 -or $cpu -ge 64) {
                throw "CPU index '$cpu' must be within 0..63"
            }
            $mask = $mask -bor ([UInt64]1 -shl $cpu)
        }
    }
    if ($mask -eq 0) {
        throw "CPU mask cannot be zero"
    }
    return $mask
}

function Quote-WinArg {
    param([string]$Value)
    if ($Value -eq "") { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}

$affinityMask = Parse-CpuMask -Spec $Cpus

$benchArgs = @(
    "perf",
    "--corpus", $Corpus,
    "--config", $Config,
    "--data-dir", $DataDir,
    "--output", $Output,
    "--suite", $Suite,
    "--stage", $Stage,
    "--repetitions", "$Repetitions",
    "--tier", "T1-emulated",
    "--cpus", $Cpus,
    "--memory-limit", "$MemoryLimitBytes",
    "--work-package", $WorkPackage,
    "--spec", $Spec
)
if ($Queries -gt 0) {
    $benchArgs += @("--queries", "$Queries")
}
if ($QueriesFile -ne "") {
    $benchArgs += @("--queries-file", $QueriesFile)
}
if ($CodeEnabled) {
    $benchArgs += "--code-enabled"
}

$exePath = if (Test-Path -LiteralPath $BenchExe) {
    (Resolve-Path -LiteralPath $BenchExe).Path
} else {
    $BenchExe
}
$cmdLine = (Quote-WinArg $exePath) + " " + (($benchArgs | ForEach-Object { Quote-WinArg $_ }) -join " ")

if ($DryRun) {
    Write-Output "T1-emulated dry run:"
    Write-Output ("  CPUs:         {0} (mask 0x{1:X})" -f $Cpus, $affinityMask)
    Write-Output ("  Memory cap:   {0} bytes ({1:N2} GiB)" -f $MemoryLimitBytes, ($MemoryLimitBytes / 1GB))
    Write-Output ("  Command line: {0}" -f $cmdLine)
    exit 0
}

if (-not (Test-Path -LiteralPath $exePath)) {
    throw "seeky-bench binary not found at '$exePath'. Build it first with: cargo build --release -p seeky-bench"
}

# Pre-flight check for heavy processes that would fail the quiet window.
$heavy = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -match '^(cargo|rustc|node|python|seeky-bench)'
}
if ($heavy) {
    $names = ($heavy | Select-Object -ExpandProperty ProcessName -Unique) -join ", "
    Write-Warning "Heavy process(es) currently running ($names). seeky-bench perf will record quiet_window.verified=false and qualifies_for_budget=false."
}

$jobHelper = @"
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class SeekyT1JobLauncher {
    private const uint CREATE_SUSPENDED = 0x00000004;
    private const uint INFINITE = 0xFFFFFFFF;
    private const int JobObjectExtendedLimitInformation = 9;
    private const uint JOB_OBJECT_LIMIT_AFFINITY = 0x00000010;
    private const uint JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100;
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput;
        public IntPtr hStdOutput;
        public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION {
        public IntPtr hProcess;
        public IntPtr hThread;
        public uint dwProcessId;
        public uint dwThreadId;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObjectW(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(
        IntPtr hJob,
        int infoType,
        ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION lpJobObjectInfo,
        uint cbJobObjectInfoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CreateProcessW(
        string lpApplicationName,
        string lpCommandLine,
        IntPtr lpProcessAttributes,
        IntPtr lpThreadAttributes,
        bool bInheritHandles,
        uint dwCreationFlags,
        IntPtr lpEnvironment,
        string lpCurrentDirectory,
        ref STARTUPINFO lpStartupInfo,
        out PROCESS_INFORMATION lpProcessInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint ResumeThread(IntPtr hThread);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(IntPtr hHandle, uint dwMilliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetExitCodeProcess(IntPtr hProcess, out uint lpExitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);

    public static int Run(string commandLine, string workingDirectory, ulong affinityMask, ulong memoryLimitBytes) {
        IntPtr job = CreateJobObjectW(IntPtr.Zero, null);
        if (job == IntPtr.Zero) {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateJobObjectW failed");
        }
        try {
            var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            info.BasicLimitInformation.LimitFlags =
                JOB_OBJECT_LIMIT_AFFINITY |
                JOB_OBJECT_LIMIT_PROCESS_MEMORY |
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            info.BasicLimitInformation.Affinity = new UIntPtr(affinityMask);
            info.ProcessMemoryLimit = new UIntPtr(memoryLimitBytes);

            uint size = (uint)Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
            if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, ref info, size)) {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "SetInformationJobObject failed");
            }

            var si = new STARTUPINFO();
            si.cb = Marshal.SizeOf(typeof(STARTUPINFO));
            PROCESS_INFORMATION pi;
            if (!CreateProcessW(
                null,
                commandLine,
                IntPtr.Zero,
                IntPtr.Zero,
                true,
                CREATE_SUSPENDED,
                IntPtr.Zero,
                workingDirectory,
                ref si,
                out pi)) {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateProcessW failed");
            }

            try {
                if (!AssignProcessToJobObject(job, pi.hProcess)) {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "AssignProcessToJobObject failed");
                }
                if (ResumeThread(pi.hThread) == 0xFFFFFFFF) {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "ResumeThread failed");
                }
                WaitForSingleObject(pi.hProcess, INFINITE);
                uint exitCode;
                if (!GetExitCodeProcess(pi.hProcess, out exitCode)) {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "GetExitCodeProcess failed");
                }
                return unchecked((int)exitCode);
            } finally {
                CloseHandle(pi.hThread);
                CloseHandle(pi.hProcess);
            }
        } finally {
            CloseHandle(job);
        }
    }
}
"@

if (-not ("SeekyT1JobLauncher" -as [type])) {
    Add-Type -TypeDefinition $jobHelper -Language CSharp
}

$highPerfGuid = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
$previousScheme = $null
if (-not $SkipPowerPlan) {
    $activeLine = (& powercfg /getactivescheme 2>$null) -join "`n"
    if ($activeLine -match '([0-9a-fA-F-]{36})') {
        $previousScheme = $Matches[1]
    }
    if ($previousScheme -and $previousScheme -ne $highPerfGuid) {
        & powercfg /setactive $highPerfGuid 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Could not activate Windows High Performance scheme ($highPerfGuid); continuing with active scheme $previousScheme."
            $previousScheme = $null
        }
    } else {
        $previousScheme = $null
    }
}

try {
    $exitCode = [SeekyT1JobLauncher]::Run($cmdLine, (Get-Location).Path, $affinityMask, $MemoryLimitBytes)
    exit $exitCode
} finally {
    if ($previousScheme) {
        & powercfg /setactive $previousScheme 2>$null
    }
}
