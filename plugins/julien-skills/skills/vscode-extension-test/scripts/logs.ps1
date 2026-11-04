<#
Prints the end of each VS Code Output channel whose log file name or extension folder contains -Match and that was
written recently, read from VS Code's log folder, so a test can check what an extension logged without opening the
Output panel.

  pwsh -NoProfile -NonInteractive -File logs.ps1 -Match 'My Extension'              # last 30 minutes
  pwsh -NoProfile -NonInteractive -File logs.ps1 -Match publisher.my-extension -Minutes 5 -Tail 80
#>
param(
  # Part of the channel name ("My Extension Server") or of the extension id ("publisher.my-extension").
  [Parameter(Mandatory)] [string] $Match,
  [int] $Minutes = 30,
  [int] $Tail = 40,
  # VS Code's log folder; Insiders writes to "Code - Insiders".
  [string] $LogRoot = (Join-Path $env:APPDATA 'Code\logs')
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $LogRoot)) { throw "no VS Code log folder at $LogRoot" }
$since = (Get-Date).AddMinutes(-$Minutes)
# Log output channels go to exthost/<extension id>/<name>.log, plain ones to exthost/output_logging_*/<n>-<name>.log.
$files = @(Get-ChildItem -LiteralPath $LogRoot -Recurse -File -Filter '*.log' -ErrorAction SilentlyContinue | Where-Object {
  $_.LastWriteTime -ge $since -and ($_.Name -like "*$Match*" -or $_.Directory.Name -like "*$Match*") } |
  Sort-Object LastWriteTime)
if (-not $files) { "no Output channel matching '$Match' written in the last $Minutes minutes under $LogRoot"; exit 1 }
foreach ($file in $files) {
  "=== $($file.FullName.Substring($LogRoot.Length + 1)) ($($file.LastWriteTime.ToString('HH:mm:ss')))"
  Get-Content -LiteralPath $file.FullName -Tail $Tail
}
