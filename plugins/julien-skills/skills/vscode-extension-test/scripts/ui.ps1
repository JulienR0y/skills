<#
Reads and operates one VS Code window through Windows UI Automation: lists the named controls it shows, presses one by
name, presses keys, types text, or closes the window. Pair it with shot.ps1 to see the result.

  pwsh -NoProfile -NonInteractive -File ui.ps1 -Window my-project -List -Filter Install
  pwsh -NoProfile -NonInteractive -File ui.ps1 -Window my-project -Press 'Install dependencies'
  pwsh -NoProfile -NonInteractive -File ui.ps1 -Window my-project -Command 'Developer: Reload Window'
  pwsh -NoProfile -NonInteractive -File ui.ps1 -Window my-project -Keys '^+p' ; -Type 'README' ; -Keys '{ENTER}'
  pwsh -NoProfile -NonInteractive -File ui.ps1 -Window my-project -Close

-List and -Press read the accessibility tree and leave the user's screen alone. -Press uses the control's own action
(Invoke, Toggle, Select or Expand); only a control without one is clicked with the mouse, which needs -AllowMouse.
-Command, -Keys, -Type and -AllowMouse bring the window to the front and take keyboard focus: tell the user first.
A native dialog the window raises is a separate window: read and answer it with the vscode-unblock skill.
#>
param(
  [Parameter(Mandatory)] [string] $Window,
  [switch] $List,
  # With -List: only controls whose name contains this text.
  [string] $Filter,
  # The exact name of the control to press, as -List prints it.
  [string] $Press,
  # Which one when several controls have that name (0 is the first -List prints).
  [int] $Index = 0,
  [switch] $AllowMouse,
  # SendKeys notation: ^ Ctrl, + Shift, % Alt, {ENTER}, {ESC}, {TAB}, {DOWN}.
  [string] $Keys,
  [string] $Type,
  # A Command Palette command, by its title as the palette lists it ("Developer: Reload Window").
  [string] $Command,
  [switch] $Close
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'window.ps1')
$target = Find-CodeWindow $Window
$CT = [System.Windows.Automation.ControlType]
$ROLES = @($CT::Button, $CT::Hyperlink, $CT::ListItem, $CT::MenuItem, $CT::CheckBox, $CT::RadioButton, $CT::TabItem,
  $CT::TreeItem, $CT::ComboBox, $CT::Edit, $CT::Text, $CT::Window)

function Get-Controls {
  $conditions = [System.Windows.Automation.Condition[]]@($ROLES | ForEach-Object {
    New-Object System.Windows.Automation.PropertyCondition($script:A::ControlTypeProperty, $_) })
  $any = New-Object System.Windows.Automation.OrCondition($conditions)
  # Chromium builds the page's accessibility tree only once a client asks, so the first query of a window can return
  # just its frame (Minimize, Maximize, Close). Ask again after a moment.
  for ($try = 0; $try -lt 3; $try++) {
    $found = @($target.Element.FindAll($script:Scope::Descendants, $any) | Where-Object {
      -not [string]::IsNullOrWhiteSpace($_.Current.Name) -and -not $_.Current.IsOffscreen })
    if ($found.Count -gt 3) { break }
    Start-Sleep -Seconds 2
  }
  foreach ($el in $found) {
    [pscustomobject]@{ Role = $el.Current.ControlType.ProgrammaticName -replace '^ControlType\.', ''; Name = $el.Current.Name; Element = $el }
  }
}

function Invoke-Control($el) {
  foreach ($pair in @(
      @([System.Windows.Automation.InvokePattern]::Pattern, { param($p) $p.Invoke() }),
      @([System.Windows.Automation.TogglePattern]::Pattern, { param($p) $p.Toggle() }),
      @([System.Windows.Automation.SelectionItemPattern]::Pattern, { param($p) $p.Select() }),
      @([System.Windows.Automation.ExpandCollapsePattern]::Pattern, { param($p) $p.Expand() }))) {
    $pattern = $null
    if ($el.TryGetCurrentPattern($pair[0], [ref]$pattern)) { & $pair[1] $pattern; return $pair[0].ProgrammaticName }
  }
  if (-not $AllowMouse) { throw 'the control has no action of its own; run again with -AllowMouse to click it' }
  $r = $el.Current.BoundingRectangle
  Show-CodeWindow $target
  [void][CodeWin]::SetCursorPos([int]($r.X + $r.Width / 2), [int]($r.Y + $r.Height / 2))
  [CodeWin]::mouse_event(0x2, 0, 0, 0, [UIntPtr]::Zero)
  [CodeWin]::mouse_event(0x4, 0, 0, 0, [UIntPtr]::Zero)
  'mouse click'
}

if ($List) {
  $controls = @(Get-Controls | Where-Object { -not $Filter -or $_.Name -like "*$Filter*" })
  $controls | ForEach-Object { '{0,-11} {1}' -f $_.Role, ($_.Name -replace '\s+', ' ') }
  "($($controls.Count) controls in '$($target.Title)')"
}
if ($Press) {
  $found = @(Get-Controls | Where-Object { ($_.Name -replace '\s+', ' ') -eq $Press })
  if ($found.Count -le $Index) { throw "no control named '$Press' (index $Index) in '$($target.Title)'; see -List" }
  $how = Invoke-Control $found[$Index].Element
  "pressed '$Press' ($($found[$Index].Role), $how)"
}
if ($Keys -or $Type -or $Command) {
  Add-Type -AssemblyName System.Windows.Forms
  $literal = { param($text) $text -replace '([+^%~(){}\[\]])', '{$1}' }
  # Keys go to whatever window is in front, so check before each send that it is still this one.
  $send = { param($text)
    if ([CodeWin]::GetForegroundWindow() -ne $target.Handle) { throw "'$($target.Title)' lost focus; nothing more was sent" }
    [System.Windows.Forms.SendKeys]::SendWait($text)
  }
  Show-CodeWindow $target
  if ($Command) {
    & $send '{F1}'; Start-Sleep -Milliseconds 700
    & $send (& $literal $Command); Start-Sleep -Milliseconds 900
    & $send '{ENTER}'
    "ran command '$Command' (check the result: a title the palette does not list runs its first match)"
  }
  if ($Type) { & $send (& $literal $Type); "typed $($Type.Length) characters" }
  if ($Keys) { & $send $Keys; "sent keys $Keys" }
}
if ($Close) {
  $pattern = $target.Element.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern)
  $pattern.Close()
  "asked '$($target.Title)' to close (a dialog may now ask to confirm: see the vscode-unblock skill)"
}
