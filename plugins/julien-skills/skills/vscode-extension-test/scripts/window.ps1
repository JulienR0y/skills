<#
Shared by shot.ps1 and ui.ps1 (dot-sourced): finds one VS Code window by its folder name, and the Win32 calls that
capture it, bring it forward and press keys or the mouse in it.
#>
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class CodeWin {
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, int dx, int dy, uint data, UIntPtr extra);
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr context);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
'@
# Per-monitor DPI awareness (-4): otherwise, above 100% scaling, Windows reports window rectangles and UI Automation
# coordinates scaled down, so a capture is cropped and a mouse click lands off target.
[void][CodeWin]::SetProcessDpiAwarenessContext([IntPtr]-4)

$script:A = [System.Windows.Automation.AutomationElement]
$script:Scope = [System.Windows.Automation.TreeScope]

# VS Code's top-level windows, as UI Automation elements with their native handle and title.
function Get-CodeWindows {
  $pids = @(Get-Process -Name Code -ErrorAction SilentlyContinue | ForEach-Object Id)
  foreach ($w in $script:A::RootElement.FindAll($script:Scope::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
    if ($pids -contains $w.Current.ProcessId -and $w.Current.Name) {
      [pscustomobject]@{ Title = $w.Current.Name; Handle = [IntPtr]$w.Current.NativeWindowHandle; Element = $w }
    }
  }
}

# The one window whose title has $Name as a whole " - " segment (VS Code titles read "<editor> - <folder> - Visual
# Studio Code"), so "my-project" does not also match "my-project.backup". Throws when none or several match.
function Find-CodeWindow([string] $Name) {
  $all = @(Get-CodeWindows)
  $match = @($all | Where-Object { ($_.Title -split ' - ') -contains $Name })
  if ($match.Count -eq 1) { return $match[0] }
  $titles = ($all | ForEach-Object { "  $($_.Title)" }) -join "`n"
  if ($match.Count -eq 0) { throw "no VS Code window has '$Name' in its title. Open windows:`n$titles" }
  throw "several VS Code windows match '$Name':`n$titles"
}

# Brings the window forward. Windows refuses SetForegroundWindow to a process that did not send the last input, so an
# F24 press and release comes first: it lifts the lock and, unlike Alt, does not open VS Code's menu bar.
function Show-CodeWindow($Window) {
  if ([CodeWin]::IsIconic($Window.Handle)) { [void][CodeWin]::ShowWindow($Window.Handle, 9) }
  for ($attempt = 0; $attempt -lt 3 -and [CodeWin]::GetForegroundWindow() -ne $Window.Handle; $attempt++) {
    [CodeWin]::keybd_event(0x87, 0, 0, [UIntPtr]::Zero)
    [CodeWin]::keybd_event(0x87, 0, 2, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 50
    [void][CodeWin]::SetForegroundWindow($Window.Handle)
    Start-Sleep -Milliseconds 250
  }
  if ([CodeWin]::GetForegroundWindow() -ne $Window.Handle) { throw "could not bring '$($Window.Title)' forward" }
}
