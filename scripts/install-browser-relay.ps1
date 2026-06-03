param(
  [switch]$Uninstall,
  [switch]$OpenSettings,
  [switch]$Machine
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$relayScript = Join-Path $repoRoot "scripts\relay-url.js"
$nodeExe = (Get-Command node.exe -ErrorAction Stop).Source
$runtimeDir = Join-Path $repoRoot ".runtime\sso-relay"
$relayExe = Join-Path $runtimeDir "MEGAntSSORelay.exe"
$relaySource = Join-Path $runtimeDir "MEGAntSSORelay.cs"

$appName = "MEGAntSSORelay"
$displayName = "MEGAnt SSO Relay"
$progId = "MEGAntSSORelayURL"
$registryHive = if ($Machine) { "HKLM:" } else { "HKCU:" }
$registeredAppsPath = if ($Machine) { "HKLM:\Software\RegisteredApplications" } else { "HKCU:\Software\RegisteredApplications" }
$classesRootPath = if ($Machine) { "HKLM:\Software\Classes" } else { "HKCU:\Software\Classes" }
$clientsRoot = "$registryHive\Software\Clients\StartMenuInternet\$appName"
$capabilities = "$clientsRoot\Capabilities"
$urlAssociations = "$capabilities\URLAssociations"
$fileAssociations = "$capabilities\FileAssociations"
$mimeAssociations = "$capabilities\MimeAssociations"
$startMenuCapabilities = "$capabilities\Startmenu"
$clientDefaultIconKey = "$clientsRoot\DefaultIcon"
$clientCommandKey = "$clientsRoot\shell\open\command"
$clientInstallInfoKey = "$clientsRoot\InstallInfo"
$applicationsRoot = "$classesRootPath\Applications\MEGAntSSORelay.exe"
$applicationsCapabilities = "$applicationsRoot\Capabilities"
$applicationsUrlAssociations = "$applicationsCapabilities\URLAssociations"
$applicationsFileAssociations = "$applicationsCapabilities\FileAssociations"
$applicationsMimeAssociations = "$applicationsCapabilities\MimeAssociations"
$applicationsCommandKey = "$applicationsRoot\shell\open\command"
$progRoot = "$classesRootPath\$progId"
$appMetaKey = "$progRoot\Application"
$defaultIconKey = "$progRoot\DefaultIcon"
$commandKey = "$progRoot\shell\open\command"
$registeredApps = $registeredAppsPath

function Escape-CSharpString([string]$Value) {
  return $Value.Replace("\", "\\").Replace('"', '\"')
}

function New-RelayExe {
  if ((Test-Path $runtimeDir) -and -not (Get-Item $runtimeDir).PSIsContainer) {
    Remove-Item -Path $runtimeDir -Force
  }
  New-Item -Path $runtimeDir -ItemType Directory -Force | Out-Null
  $node = Escape-CSharpString $nodeExe
  $script = Escape-CSharpString $relayScript
  $source = @"
using System;
using System.Diagnostics;

[assembly: System.Reflection.AssemblyTitle("MEGAnt SSO Relay")]
[assembly: System.Reflection.AssemblyDescription("Relay DingTalk SSO URLs to the local MEGAnt Playwright Edge session.")]
[assembly: System.Reflection.AssemblyCompany("MEGAnt")]
[assembly: System.Reflection.AssemblyProduct("MEGAnt SSO Relay")]

public static class Program
{
  public static int Main(string[] args)
  {
    if (args.Length == 0) return 2;
    var start = new ProcessStartInfo();
    start.FileName = "$node";
    start.Arguments = "\"" + "$script" + "\" \"" + args[0].Replace("\"", "\\\"") + "\"";
    start.UseShellExecute = false;
    start.CreateNoWindow = true;
    Process.Start(start);
    return 0;
  }
}
"@
  Set-Content -Path $relaySource -Value $source -Encoding UTF8
  Add-Type -TypeDefinition $source -OutputAssembly $relayExe -OutputType WindowsApplication
}

function Ensure-RegKey([string]$Path) {
  if (!(Test-Path $Path)) {
    New-Item -Path $Path -Force | Out-Null
  }
}

function Set-DefaultValue([string]$Path, [string]$Value) {
  Set-Item -Path $Path -Value $Value
}

function Remove-RelayRegistration {
  Remove-Item -Path $clientsRoot -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -Path $applicationsRoot -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -Path $progRoot -Recurse -Force -ErrorAction SilentlyContinue
  Remove-ItemProperty -Path $registeredApps -Name $appName -ErrorAction SilentlyContinue
  Remove-ItemProperty -Path $registeredApps -Name $displayName -ErrorAction SilentlyContinue
  Remove-Item -Path $runtimeDir -Recurse -Force -ErrorAction SilentlyContinue
}

function Assert-RelayRegistration {
  $registered = (Get-ItemProperty -Path $registeredApps -ErrorAction Stop).$appName
  if ($registered -ne "Software\Clients\StartMenuInternet\$appName\Capabilities") {
    $scope = if ($Machine) { "machine-wide HKLM" } else { "current-user HKCU" }
    throw "Relay is not registered in $scope RegisteredApplications."
  }
  if (!(Test-Path $capabilities)) {
    throw "Relay Capabilities key was not created: $capabilities"
  }
  if (!(Test-Path $commandKey)) {
    throw "Relay command key was not created: $commandKey"
  }
  if (!(Test-Path $startMenuCapabilities)) {
    throw "Relay Startmenu capability key was not created: $startMenuCapabilities"
  }
  if (!(Test-Path $fileAssociations)) {
    throw "Relay FileAssociations key was not created: $fileAssociations"
  }
  $urlAssoc = Get-ItemProperty -Path $urlAssociations -ErrorAction Stop
  if ($urlAssoc.http -ne $progId -or $urlAssoc.https -ne $progId) {
    throw "Relay HTTP/HTTPS URL associations were not registered."
  }
}

if ($Uninstall) {
  Remove-RelayRegistration
  Write-Output "MEGAnt SSO relay registration removed."
  if ($OpenSettings) {
    Start-Process "ms-settings:defaultapps"
  }
  exit 0
}

if (!(Test-Path $relayScript)) {
  throw "Relay script not found: $relayScript"
}

New-RelayExe

Ensure-RegKey $clientsRoot
Ensure-RegKey $capabilities
Ensure-RegKey $urlAssociations
Ensure-RegKey $fileAssociations
Ensure-RegKey $mimeAssociations
Ensure-RegKey $startMenuCapabilities
Ensure-RegKey $clientDefaultIconKey
Ensure-RegKey $clientCommandKey
Ensure-RegKey $clientInstallInfoKey
Ensure-RegKey $applicationsRoot
Ensure-RegKey $applicationsCapabilities
Ensure-RegKey $applicationsUrlAssociations
Ensure-RegKey $applicationsFileAssociations
Ensure-RegKey $applicationsMimeAssociations
Ensure-RegKey $applicationsCommandKey
Ensure-RegKey $appMetaKey
Ensure-RegKey $defaultIconKey
Ensure-RegKey $commandKey
Ensure-RegKey $registeredApps

Set-DefaultValue $clientsRoot $displayName
Set-ItemProperty -Path $clientsRoot -Name "LocalizedString" -Value $displayName
Set-ItemProperty -Path $capabilities -Name "ApplicationIcon" -Value "$relayExe,0"
Set-ItemProperty -Path $capabilities -Name "ApplicationName" -Value $displayName
Set-ItemProperty -Path $capabilities -Name "ApplicationDescription" -Value "Relay DingTalk SSO URLs to the local MEGAnt Playwright Edge session."
Set-ItemProperty -Path $urlAssociations -Name "http" -Value $progId
Set-ItemProperty -Path $urlAssociations -Name "https" -Value $progId
Set-ItemProperty -Path $fileAssociations -Name ".htm" -Value $progId
Set-ItemProperty -Path $fileAssociations -Name ".html" -Value $progId
Set-ItemProperty -Path $fileAssociations -Name ".shtml" -Value $progId
Set-ItemProperty -Path $fileAssociations -Name ".xht" -Value $progId
Set-ItemProperty -Path $fileAssociations -Name ".xhtml" -Value $progId
Set-ItemProperty -Path $mimeAssociations -Name "text/html" -Value $progId
Set-ItemProperty -Path $mimeAssociations -Name "application/xhtml+xml" -Value $progId
Set-ItemProperty -Path $startMenuCapabilities -Name "StartMenuInternet" -Value $appName
Set-ItemProperty -Path $registeredApps -Name $appName -Value "Software\Clients\StartMenuInternet\$appName\Capabilities"
Set-ItemProperty -Path $registeredApps -Name $displayName -Value "Software\Classes\Applications\MEGAntSSORelay.exe\Capabilities"

Set-DefaultValue $clientDefaultIconKey "$relayExe,0"
Set-DefaultValue $clientCommandKey "`"$relayExe`""
Set-ItemProperty -Path $clientInstallInfoKey -Name "IconsVisible" -Value 1
Set-ItemProperty -Path $clientInstallInfoKey -Name "ReinstallCommand" -Value "`"$relayExe`""

Set-DefaultValue $applicationsRoot $displayName
Set-ItemProperty -Path $applicationsCapabilities -Name "ApplicationIcon" -Value "$relayExe,0"
Set-ItemProperty -Path $applicationsCapabilities -Name "ApplicationName" -Value $displayName
Set-ItemProperty -Path $applicationsCapabilities -Name "ApplicationDescription" -Value "Relay DingTalk SSO URLs to the local MEGAnt Playwright Edge session."
Set-ItemProperty -Path $applicationsUrlAssociations -Name "http" -Value $progId
Set-ItemProperty -Path $applicationsUrlAssociations -Name "https" -Value $progId
Set-ItemProperty -Path $applicationsFileAssociations -Name ".htm" -Value $progId
Set-ItemProperty -Path $applicationsFileAssociations -Name ".html" -Value $progId
Set-ItemProperty -Path $applicationsFileAssociations -Name ".shtml" -Value $progId
Set-ItemProperty -Path $applicationsFileAssociations -Name ".xht" -Value $progId
Set-ItemProperty -Path $applicationsFileAssociations -Name ".xhtml" -Value $progId
Set-ItemProperty -Path $applicationsMimeAssociations -Name "text/html" -Value $progId
Set-ItemProperty -Path $applicationsMimeAssociations -Name "application/xhtml+xml" -Value $progId
Set-DefaultValue $applicationsCommandKey "`"$relayExe`" `"%1`""

Set-DefaultValue $progRoot "MEGAnt SSO Relay URL"
Set-ItemProperty -Path $progRoot -Name "URL Protocol" -Value ""
Set-ItemProperty -Path $appMetaKey -Name "ApplicationName" -Value $displayName
Set-ItemProperty -Path $appMetaKey -Name "ApplicationDescription" -Value "Relay DingTalk SSO URLs to MEGAnt."
Set-ItemProperty -Path $appMetaKey -Name "ApplicationCompany" -Value "MEGAnt"
Set-DefaultValue $defaultIconKey "`"$relayExe`",0"
Set-DefaultValue $commandKey "`"$relayExe`" `"%1`""

Assert-RelayRegistration

Write-Output "MEGAnt SSO relay registered."
Write-Output "Relay executable: $relayExe"
if ($Machine) {
  Write-Output "Machine-wide registry verified: HKLM\Software\RegisteredApplications\$appName"
} else {
  Write-Output "Current-user registry verified: HKCU\Software\RegisteredApplications\$appName"
  Write-Output "Important: run this installer without administrator elevation, otherwise HKCU may point at the wrong user."
  Write-Output "If Windows Default apps still does not list it, run from an administrator PowerShell with: powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install-browser-relay.ps1 -Machine -OpenSettings"
}
Write-Output "Next: open Windows Settings > Apps > Default apps, choose 'MEGAnt SSO Relay', and set HTTP/HTTPS to it."
Write-Output "After testing, switch HTTP/HTTPS default apps back to Microsoft Edge."

if ($OpenSettings) {
  Start-Process "ms-settings:defaultapps"
}
