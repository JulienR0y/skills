<#
Saves one VS Code window as a PNG, to look at with an image viewer tool. Uses PrintWindow, so a window covered by
other windows is still captured as it renders (not a minimized one) and the user's screen is left alone.

  pwsh -NoProfile -NonInteractive -File shot.ps1 -Window my-project -Out "$env:TEMP\shots\01-report.png"
  pwsh -NoProfile -NonInteractive -File shot.ps1 -List
#>
param(
  [string] $Window,
  [string] $Out,
  # Scaled down to this width, so the image stays readable without costing a full-resolution image. 0 keeps it as is.
  [int] $Width = 1600,
  [switch] $List
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'window.ps1')
Add-Type -AssemblyName System.Drawing

if ($List) { Get-CodeWindows | ForEach-Object { $_.Title }; exit 0 }
if (-not $Window -or -not $Out) { throw 'usage: shot.ps1 -Window <folder name> -Out <file.png> [-Width 1600] | -List' }

$target = Find-CodeWindow $Window
if ([CodeWin]::IsIconic($target.Handle)) { throw "'$($target.Title)' is minimized; restore it first (a minimized window has nothing to capture)" }
$rect = New-Object CodeWin+RECT
[void][CodeWin]::GetWindowRect($target.Handle, [ref]$rect)
$w = $rect.Right - $rect.Left; $h = $rect.Bottom - $rect.Top
if ($w -le 0 -or $h -le 0) { throw "'$($target.Title)' has no area" }

$bitmap = New-Object System.Drawing.Bitmap $w, $h
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$hdc = $graphics.GetHdc()
# PW_RENDERFULLCONTENT: without it an Electron window captures as black.
$ok = [CodeWin]::PrintWindow($target.Handle, $hdc, 2)
$graphics.ReleaseHdc($hdc); $graphics.Dispose()
if (-not $ok) { $bitmap.Dispose(); throw "PrintWindow failed for '$($target.Title)'" }

if ($Width -gt 0 -and $w -gt $Width) {
  $scaled = New-Object System.Drawing.Bitmap $Width, ([int]($h * $Width / $w))
  $g = [System.Drawing.Graphics]::FromImage($scaled)
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.DrawImage($bitmap, 0, 0, $scaled.Width, $scaled.Height); $g.Dispose(); $bitmap.Dispose()
  $bitmap = $scaled
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent ([IO.Path]::GetFullPath($Out))) | Out-Null
$bitmap.Save([IO.Path]::GetFullPath($Out), [System.Drawing.Imaging.ImageFormat]::Png)
"{0} ({1}x{2}) <- {3}" -f [IO.Path]::GetFullPath($Out), $bitmap.Width, $bitmap.Height, $target.Title
$bitmap.Dispose()
