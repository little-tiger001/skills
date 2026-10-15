# Render PPTX slides to PNG via WPS / PowerPoint COM automation.
# Fallback for hosts without the DSH bundled LibreOffice Kit.
# Usage: powershell -File render_wps.ps1 -Source deck.pptx -OutputDir preview [-Pages 1,3-5]
param(
  [Parameter(Mandatory = $true)][string]$Source,
  [Parameter(Mandatory = $true)][string]$OutputDir,
  [string]$Pages = "",
  [int]$Width = 1600,
  [int]$Height = 900
)

$ErrorActionPreference = "Stop"
$src = (Resolve-Path -LiteralPath $Source).Path
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$OutputDir = (Resolve-Path -LiteralPath $OutputDir).Path

$app = $null
foreach ($progId in @("KWPP.Application", "PowerPoint.Application")) {
  try { $app = New-Object -ComObject $progId; Write-Output "engine=$progId"; break } catch { }
}
if ($null -eq $app) { Write-Error "No WPS or PowerPoint COM automation available"; exit 1 }

$wanted = @()
if ($Pages -ne "") {
  foreach ($part in $Pages.Split(",")) {
    $part = $part.Trim()
    if ($part -match "^(\d+)-(\d+)$") {
      $wanted += ([int]$Matches[1])..([int]$Matches[2])
    } elseif ($part -match "^\d+$") {
      $wanted += [int]$part
    }
  }
}

$app.Visible = $true
$pres = $app.Presentations.Open($src, $true, $false, $false)
try {
  $count = $pres.Slides.Count
  for ($i = 1; $i -le $count; $i++) {
    if ($wanted.Count -gt 0 -and $wanted -notcontains $i) { continue }
    $file = Join-Path $OutputDir ("slide-{0:D2}.png" -f $i)
    $pres.Slides.Item($i).Export($file, "PNG", $Width, $Height)
    Write-Output $file
  }
} finally {
  $pres.Close()
  $app.Quit()
}
exit 0
