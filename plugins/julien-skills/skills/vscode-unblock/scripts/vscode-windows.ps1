<#
Lists VS Code's top-level windows, and the text and buttons of any dialog one of them shows, through UI Automation
(read-only). With -Press, invokes that one button on the dialog whose text matches -Dialog.

  pwsh -NoProfile -NonInteractive -File vscode-windows.ps1
  pwsh -NoProfile -NonInteractive -File vscode-windows.ps1 -Dialog 'terminate' -Press 'Cancel'
#>
param([string]$Dialog, [string]$Press)

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$T = [System.Windows.Automation.TreeScope]
$C = [System.Windows.Automation.Condition]::TrueCondition
$codePids = @(Get-Process -Name Code -ErrorAction SilentlyContinue | ForEach-Object Id)
if (-not $codePids) { Write-Output 'no Code.exe process'; exit 0 }

$byType = { param($el, $type)
  $el.FindAll($T::Descendants, (New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, $type)))
}
# A task dialog with command links (Electron's showMessageBox with custom buttons, as an extension's modal report
# with its own buttons uses) shows each button as a CCPushButton pane with no Invoke pattern, AutomationId
# CommandButton_<id>. TDM_CLICK_BUTTON presses it by that id without taking focus.
$dialogButtons = { param($d)
  @(& $byType $d ([System.Windows.Automation.ControlType]::Button)) +
  @(& $byType $d ([System.Windows.Automation.ControlType]::Pane) | Where-Object { $_.Current.ClassName -eq 'CCPushButton' })
}
$pressButton = { param($d, $button)
  $invoke = $null
  if ($button.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$invoke)) { $invoke.Invoke(); return }
  $id = [regex]::Match($button.Current.AutomationId, '^CommandButton_(\d+)$')
  if (-not $id.Success) { throw "button '$($button.Current.Name)' cannot be pressed" }
  Add-Type -Namespace TaskDialog -Name Native -MemberDefinition @'
[DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam, uint flags, uint timeout, out IntPtr result);
[DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hWnd);
'@
  $handle = [IntPtr]$d.Current.NativeWindowHandle
  $result = [IntPtr]::Zero
  # SMTO_ABORTIFHUNG, 5 s: returns once the dialog handled the click, and never waits on a hung window.
  if ([TaskDialog.Native]::SendMessageTimeout($handle, 0x466, [IntPtr][int]$id.Groups[1].Value, [IntPtr]::Zero, 2, 5000, [ref]$result) -eq [IntPtr]::Zero) {
    throw "the dialog did not take the click on '$($button.Current.Name)'"
  }
  Start-Sleep -Milliseconds 500
  if ([TaskDialog.Native]::IsWindow($handle)) { throw "the dialog is still open after the click on '$($button.Current.Name)'" }
}
$found = $false
foreach ($w in $A::RootElement.FindAll($T::Children, $C)) {
  if ($codePids -notcontains $w.Current.ProcessId) { continue }
  Write-Output ("window  pid={0} class={1} title={2}" -f $w.Current.ProcessId, $w.Current.ClassName, $w.Current.Name)
  # Both a native message box and VS Code's own in-page dialogs ("A session is in progress...") show as a Window
  # element under their VS Code window.
  $dialogs = @(& $byType $w ([System.Windows.Automation.ControlType]::Window)) + @(if ($w.Current.ClassName -eq '#32770') { $w })
  foreach ($d in $dialogs) {
    $texts = @(& $byType $d ([System.Windows.Automation.ControlType]::Text) | ForEach-Object { $_.Current.Name } | Where-Object { $_ })
    $buttons = @(& $dialogButtons $d)
    $names = @($buttons | ForEach-Object { $_.Current.Name } | Where-Object { $_ })
    Write-Output ("  dialog title={0}" -f $d.Current.Name)
    $texts | ForEach-Object { Write-Output "    text: $_" }
    Write-Output ("    buttons: {0}" -f ($names -join ' | '))
    $all = ($d.Current.Name + ' ' + ($texts -join ' '))
    if ($Press -and $Dialog -and $all -match [regex]::Escape($Dialog)) {
      $target = $buttons | Where-Object { $_.Current.Name -eq $Press } | Select-Object -First 1
      if (-not $target) { Write-Output "    no button named '$Press'"; exit 1 }
      try { & $pressButton $d $target } catch { Write-Output "    not pressed: $($_.Exception.Message)"; exit 1 }
      Write-Output "    pressed: $Press"
      $found = $true
    }
  }
}
if ($Press -and -not $found) { Write-Output "no dialog matching '$Dialog'"; exit 1 }
