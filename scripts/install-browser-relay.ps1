param(
  [switch]$Uninstall,
  [switch]$OpenSettings
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$relayScript = Join-Path $repoRoot "scripts\relay-url.js"
$nodeExe = (Get-Command node.exe -ErrorAction Stop).Source
$runtimeDir = Join-Path $repoRoot ".runtime\sso-relay"
$relayExe = Join-Path $runtimeDir "MEGAntSSORelay.exe"
$relaySource = Join-Path $runtimeDir "MEGAntSSORelay.cs"

$appName = "MEGAntSSORelay"
$progId = "MEGAntSSORelayURL"
$clientsRoot = "HKCU:\Software\Clients\StartMenuInternet\$appName"
$capabilities = "$clientsRoot\Capabilities"
$urlAssociations = "$capabilities\URLAssociations"
$progRoot = "HKCU:\Software\Classes\$progId"
$appMetaKey = "$progRoot\Application"
$defaultIconKey = "$progRoot\DefaultIcon"
$commandKey = "$progRoot\shell\open\command"
$registeredApps = "HKCU:\Software\RegisteredApplications"

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

function Remove-RelayRegistration {
  Remove-Item -Path $clientsRoot -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -Path $progRoot -Recurse -Force -ErrorAction SilentlyContinue
  Remove-ItemProperty -Path $registeredApps -Name $appName -ErrorAction SilentlyContinue
  Remove-Item -Path $runtimeDir -Recurse -Force -ErrorAction SilentlyContinue
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

New-Item -Path $clientsRoot -Force | Out-Null
New-Item -Path $capabilities -Force | Out-Null
New-Item -Path $urlAssociations -Force | Out-Null
New-Item -Path $appMetaKey -Force | Out-Null
New-Item -Path $defaultIconKey -Force | Out-Null
New-Item -Path $commandKey -Force | Out-Null
New-Item -Path $registeredApps -Force | Out-Null

Set-Item -Path $clientsRoot -Value "MEGAnt SSO Relay"
Set-ItemProperty -Path $clientsRoot -Name "LocalizedString" -Value "MEGAnt SSO Relay"
Set-ItemProperty -Path $capabilities -Name "ApplicationIcon" -Value $relayExe
Set-ItemProperty -Path $capabilities -Name "ApplicationName" -Value "MEGAnt SSO Relay"
Set-ItemProperty -Path $capabilities -Name "ApplicationDescription" -Value "Relay DingTalk SSO URLs to the local MEGAnt Playwright Edge session."
Set-ItemProperty -Path $urlAssociations -Name "http" -Value $progId
Set-ItemProperty -Path $urlAssociations -Name "https" -Value $progId
Set-ItemProperty -Path $registeredApps -Name $appName -Value "Software\Clients\StartMenuInternet\$appName\Capabilities"

Set-Item -Path $progRoot -Value "MEGAnt SSO Relay URL"
Set-ItemProperty -Path $progRoot -Name "URL Protocol" -Value ""
Set-ItemProperty -Path $appMetaKey -Name "ApplicationName" -Value "MEGAnt SSO Relay"
Set-ItemProperty -Path $appMetaKey -Name "ApplicationDescription" -Value "Relay DingTalk SSO URLs to MEGAnt."
Set-ItemProperty -Path $appMetaKey -Name "ApplicationCompany" -Value "MEGAnt"
Set-Item -Path $defaultIconKey -Value "`"$relayExe`",0"
Set-Item -Path $commandKey -Value "`"$relayExe`" `"%1`""

Write-Output "MEGAnt SSO relay registered."
Write-Output "Relay executable: $relayExe"
Write-Output "Next: open Windows Settings > Apps > Default apps, choose 'MEGAnt SSO Relay', and set HTTP/HTTPS to it."
Write-Output "After testing, switch HTTP/HTTPS default apps back to Microsoft Edge."

if ($OpenSettings) {
  Start-Process "ms-settings:defaultapps"
}
