<#
.SYNOPSIS
Inspect Super Productivity plugins on this machine.

.DESCRIPTION
Read-only with respect to the installed app: reads resources\app.asar and the
IndexedDB LevelDB files, never writes to them.

  list     list bundled plugins (inside app.asar) and uploaded plugin traces (IndexedDB)
  cat      print one file of a bundled plugin
  extract  copy every file of a bundled plugin into a directory

.PARAMETER PluginId
Bundled plugin folder name, e.g. api-test-plugin.

.PARAMETER File
Path inside the plugin, e.g. manifest.json or plugin.js. Required by -Action cat.

.PARAMETER OutDir
Destination directory. Required by -Action extract. Created if missing.

.PARAMETER AppRoot
Super Productivity install directory. Defaults to the per-user install.

.EXAMPLE
sp-plugins.ps1 -Action list
.EXAMPLE
sp-plugins.ps1 -Action cat -PluginId api-test-plugin -File manifest.json
.EXAMPLE
sp-plugins.ps1 -Action extract -PluginId automations -OutDir .\sp-automations
#>
[CmdletBinding()]
param(
  [ValidateSet('list', 'cat', 'extract')][string]$Action = 'list',
  [string]$PluginId,
  [string]$File,
  [string]$OutDir,
  [string]$AppRoot = "$env:LOCALAPPDATA\Programs\Super Productivity"
)

$ErrorActionPreference = 'Stop'
$AsarPath = Join-Path $AppRoot 'resources\app.asar'
if (-not (Test-Path -LiteralPath $AsarPath)) { throw "app.asar not found: $AsarPath" }

function Get-AsarArchive {
  $fs = [System.IO.FileStream]::new($AsarPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
  try {
    $head = New-Object byte[] 16
    if ($fs.Read($head, 0, 16) -ne 16) { throw 'app.asar header is truncated' }
    $jsonLen = [BitConverter]::ToUInt32($head, 12)
    $jb = New-Object byte[] $jsonLen
    $got = 0
    while ($got -lt $jsonLen) {
      $n = $fs.Read($jb, $got, $jsonLen - $got)
      if ($n -le 0) { break }
      $got += $n
    }
    if ($got -ne $jsonLen) { throw 'app.asar JSON header is truncated' }
    $root = ([System.Text.Encoding]::UTF8.GetString($jb) | ConvertFrom-Json).files
    $entries = New-Object System.Collections.Generic.List[object]
    Add-AsarEntries -Node $root -Prefix '' -Entries $entries
    return [pscustomobject]@{ Stream = $fs; Base = 16 + $jsonLen; Entries = $entries }
  }
  catch { $fs.Dispose(); throw }
}

function Add-AsarEntries {
  param($Node, [string]$Prefix, $Entries)
  foreach ($p in $Node.PSObject.Properties) {
    if ($p.Name -eq 'files') { Add-AsarEntries -Node $p.Value -Prefix $Prefix -Entries $Entries; continue }
    $v = $p.Value
    if ($v.files) { Add-AsarEntries -Node $v.files -Prefix "$Prefix$($p.Name)/" -Entries $Entries }
    else { $Entries.Add([pscustomobject]@{ Path = "$Prefix$($p.Name)"; Offset = [int64]$v.offset; Size = [int64]$v.size }) }
  }
}

function Read-AsarEntry {
  param($Archive, $Entry)
  if ($Entry.Size -eq 0) { return New-Object byte[] 0 }
  $Archive.Stream.Seek($Archive.Base + $Entry.Offset, [System.IO.SeekOrigin]::Begin) | Out-Null
  $buf = New-Object byte[] $Entry.Size
  $got = 0
  while ($got -lt $Entry.Size) {
    $n = $Archive.Stream.Read($buf, $got, $Entry.Size - $got)
    if ($n -le 0) { break }
    $got += $n
  }
  return $buf
}

function Read-TextFileShared {
  param([string]$Path)
  try {
    $fs = [System.IO.FileStream]::new($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
      $buf = New-Object byte[] $fs.Length
      $got = 0
      while ($got -lt $buf.Length) {
        $n = $fs.Read($buf, $got, $buf.Length - $got)
        if ($n -le 0) { break }
        $got += $n
      }
      return [System.Text.Encoding]::UTF8.GetString($buf, 0, $got)
    }
    finally { $fs.Dispose() }
  }
  catch { return $null }
}

$archive = Get-AsarArchive
try {
  $bundled = $archive.Entries | Where-Object { $_.Path -match 'bundled-plugins/([^/]+)/' }
  $ids = $bundled | ForEach-Object { [regex]::Match($_.Path, 'bundled-plugins/([^/]+)/').Groups[1].Value } | Sort-Object -Unique
  $manifestPath = ($archive.Entries | Where-Object { $_.Path -match 'assets/community-plugins\.json$' } | Select-Object -First 1).Path

  switch ($Action) {
    'list' {
      "app.asar : $AsarPath"
      $appExe = Join-Path $AppRoot 'Super Productivity.exe'
      if (Test-Path -LiteralPath $appExe) { "app ver  : $((Get-Item -LiteralPath $appExe).VersionInfo.ProductVersion)" }
      ""
      "BUNDLED PLUGINS ($($ids.Count)) - shipped inside app.asar, version-matched to this install"
      foreach ($id in $ids) {
        $mf = $bundled | Where-Object { $_.Path -eq ".tmp/angular-dist/browser/assets/bundled-plugins/$id/manifest.json" } | Select-Object -First 1
        if (-not $mf) { $mf = $bundled | Where-Object { $_.Path -match "bundled-plugins/$([regex]::Escape($id))/manifest\.json$" } | Select-Object -First 1 }
        $name = ''; $ver = ''; $min = ''
        if ($mf) {
          try {
            $m = [System.Text.Encoding]::UTF8.GetString((Read-AsarEntry -Archive $archive -Entry $mf)) | ConvertFrom-Json
            $name = $m.name; $ver = $m.version; $min = $m.minSupVersion
          }
          catch { $name = '<unreadable manifest>' }
        }
        "  {0,-32} {1,-10} minSup {2,-8} {3}" -f $id, $ver, $min, $name
      }
      ""
      "COMMUNITY LIST - bundled snapshot of the curated community plugin list"
      if ($manifestPath) { "  source : $manifestPath (inside app.asar)" }
      "  remote : https://github.com/super-productivity/super-productivity/blob/master/src/assets/community-plugins.json"
      ""
      "UPLOADED PLUGINS - user-installed ZIPs live in IndexedDB, not on disk"
      $idbDir = Join-Path $env:APPDATA 'superProductivity\IndexedDB'
      if (Test-Path -LiteralPath $idbDir) {
        $ids2 = New-Object System.Collections.Generic.HashSet[string]
        foreach ($lf in Get-ChildItem -LiteralPath $idbDir -Recurse -File -Force -ErrorAction SilentlyContinue) {
          $txt = Read-TextFileShared -Path $lf.FullName
          if (-not $txt) { continue }
          foreach ($m in [regex]::Matches($txt, 'uploaded://([A-Za-z0-9_.\-]+)')) { [void]$ids2.Add($m.Groups[1].Value) }
        }
        if ($ids2.Count -eq 0) { "  none found (no uploaded:// marker in IndexedDB)" }
        else { foreach ($i in ($ids2 | Sort-Object)) { "  $i" } }
        "  note   : enabled/disabled state is also IndexedDB-only; confirm in Settings -> Plugins"
      }
      else { "  IndexedDB directory not found: $idbDir" }
    }

    'cat' {
      if (-not $PluginId) { throw '-PluginId is required for -Action cat' }
      if (-not $File) { throw '-File is required for -Action cat' }
      $want = "bundled-plugins/$PluginId/$File"
      $e = $bundled | Where-Object { $_.Path.EndsWith($want) } | Select-Object -First 1
      if (-not $e) {
        $avail = ($bundled | Where-Object { $_.Path -match "bundled-plugins/$([regex]::Escape($PluginId))/" } | ForEach-Object { $_.Path -replace '.*/bundled-plugins/[^/]+/', '' }) -join ', '
        throw "not found: $want. Files in '$PluginId': $avail"
      }
      [System.Text.Encoding]::UTF8.GetString((Read-AsarEntry -Archive $archive -Entry $e))
    }

    'extract' {
      if (-not $PluginId) { throw '-PluginId is required for -Action extract' }
      if (-not $OutDir) { throw '-OutDir is required for -Action extract' }
      $mine = $bundled | Where-Object { $_.Path -match "bundled-plugins/$([regex]::Escape($PluginId))/" }
      if (-not $mine) { throw "bundled plugin not found: $PluginId. Run -Action list." }
      $dest = (New-Item -ItemType Directory -Force -Path $OutDir).FullName
      foreach ($e in $mine) {
        $rel = $e.Path -replace '.*/bundled-plugins/[^/]+/', ''
        $target = Join-Path $dest ($rel -replace '/', [System.IO.Path]::DirectorySeparatorChar)
        $parent = Split-Path -Parent $target
        if ($parent -and -not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
        [System.IO.File]::WriteAllBytes($target, (Read-AsarEntry -Archive $archive -Entry $e))
      }
      "extracted $($mine.Count) files -> $dest"
    }
  }
}
finally { $archive.Stream.Dispose() }
