param(
    [ValidateSet("chrome", "firefox", "all")]
    [string]$Target = "chrome",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$ExtensionDir = Join-Path $RepoRoot "extension"
$FirefoxExtensionDir = Join-Path $RepoRoot "extension-firefox"
$AuditScript = Join-Path $ScriptDir "audit_eazyfill_packages.ps1"

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $ExtensionDir "dist"
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)

function Get-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-ChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent
    )

    $fullPath = Get-FullPath $Path
    $fullParent = (Get-FullPath $Parent).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $prefix = $fullParent + [System.IO.Path]::DirectorySeparatorChar
    if (!$fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify path outside package output: $fullPath"
    }
}

function Remove-PackagePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    Assert-ChildPath -Path $Path -Parent $OutputDir
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Get-RelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $base = (Get-FullPath $BasePath).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $fullPath = Get-FullPath $Path
    $prefix = $base + [System.IO.Path]::DirectorySeparatorChar
    if (!$fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside expected base directory: $fullPath"
    }
    return $fullPath.Substring($prefix.Length).Replace("\", "/")
}

function Get-PackageBlockReason {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $path = $RelativePath.Replace("\", "/").TrimStart("/")
    $segments = @($path.Split("/") | Where-Object { $_.Length -gt 0 })
    $leaf = if ($segments.Count -gt 0) { $segments[-1] } else { "" }
    $extension = [System.IO.Path]::GetExtension($leaf).ToLowerInvariant()

    if ($path -match "(^|/)\.\.(/|$)" -or $RelativePath.StartsWith("/") -or $RelativePath -match "^[A-Za-z]:") {
        return "unsafe path"
    }
    if ($path -in @("background.js", "content.js", "locator_picker.js") -or $path.StartsWith("modules/", [System.StringComparison]::OrdinalIgnoreCase)) {
        return "legacy root source"
    }
    if ($segments | Where-Object { $_ -in @("dist", "node_modules") }) {
        return "nested build or dependency directory"
    }
    if ($leaf -ieq ".gitkeep") {
        return "repository placeholder"
    }
    if ($leaf -ieq ".env" -or $leaf.StartsWith(".env.", [System.StringComparison]::OrdinalIgnoreCase)) {
        return "environment file"
    }
    if ($extension -eq ".bak") {
        return "backup file"
    }
    if ($extension -eq ".map") {
        return "source map"
    }
    if ($extension -in @(".pem", ".key", ".crt", ".cer", ".cert", ".pfx", ".p12", ".pkcs12", ".p7b", ".p7c", ".der", ".jks", ".keystore", ".pub")) {
        return "private key or certificate"
    }
    if ($leaf -match "^(?i:id_(rsa|dsa|ecdsa|ed25519)|private[-_.]?key)$") {
        return "private key or certificate"
    }
    if ($segments | Where-Object { $_ -match "^(?i:test(s)?|__tests__|fixture(s)?|test[-_]?data|private|private[-_]?data|secret(s)?)$" }) {
        return "test fixture or private data"
    }
    if ($path -match "(?i)flowpilot") {
        return "stale FlowPilot artifact"
    }
    return $null
}

function Test-SensitiveFileContent {
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $length = [System.Math]::Min(16384, [int]$stream.Length)
        if ($length -eq 0) {
            return $false
        }
        $buffer = New-Object byte[] $length
        $read = $stream.Read($buffer, 0, $buffer.Length)
        $text = [System.Text.Encoding]::ASCII.GetString($buffer, 0, $read)
        return $text -match "-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----|-----BEGIN CERTIFICATE-----|PuTTY-User-Key-File-"
    } finally {
        $stream.Dispose()
    }
}

function Get-ManifestVersion {
    param([Parameter(Mandatory = $true)][string]$ManifestPath)
    $manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
    return [string]$manifest.version
}

function Copy-PackageFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$BuildDir
    )

    $reason = Get-PackageBlockReason $RelativePath
    if ($reason -in @("repository placeholder", "backup file", "source map")) {
        Write-Verbose "Excluded $RelativePath ($reason)"
        return
    }
    if ($reason) {
        throw "Refusing to package $RelativePath ($reason)"
    }
    if (Test-SensitiveFileContent $Source) {
        throw "Refusing to package $RelativePath (embedded private key or certificate)"
    }

    $destination = Join-Path $BuildDir ($RelativePath.Replace("/", "\"))
    $destinationDir = Split-Path -Parent $destination
    New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
    Copy-Item -LiteralPath $Source -Destination $destination -Force
}

function Copy-EazyFillSource {
    param(
        [Parameter(Mandatory = $true)][string]$BuildDir,
        [Parameter(Mandatory = $true)][string]$ExtensionSourceDir
    )

    Remove-PackagePath $BuildDir
    New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null

    $directories = @(
        "_locales",
        "background",
        "content",
        "icons",
        "lib",
        "options",
        "popup",
        "userscripts"
    )

    foreach ($directory in $directories) {
        $sourceDir = Join-Path $ExtensionSourceDir $directory
        if (!(Test-Path -LiteralPath $sourceDir -PathType Container)) {
            throw "Required extension directory is missing: $sourceDir"
        }
        foreach ($file in @(Get-ChildItem -LiteralPath $sourceDir -File -Recurse -Force)) {
            $relativePath = Get-RelativePath -BasePath $ExtensionSourceDir -Path $file.FullName
            Copy-PackageFile -Source $file.FullName -RelativePath $relativePath -BuildDir $BuildDir
        }
    }

    Copy-PackageFile -Source (Join-Path $ExtensionSourceDir "manifest.json") -RelativePath "manifest.json" -BuildDir $BuildDir
    Copy-PackageFile -Source (Join-Path $ExtensionSourceDir "favicon.svg") -RelativePath "favicon.svg" -BuildDir $BuildDir
}

function New-DeterministicZip {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDir,
        [Parameter(Mandatory = $true)][string]$ArchivePath
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    Remove-PackagePath $ArchivePath
    $sourceRoot = Get-FullPath $SourceDir
    $fileByPath = @{}
    foreach ($file in @(Get-ChildItem -LiteralPath $sourceRoot -File -Recurse -Force)) {
        $relativePath = Get-RelativePath -BasePath $sourceRoot -Path $file.FullName
        $reason = Get-PackageBlockReason $relativePath
        if ($reason) {
            throw "Staged package contains forbidden entry $relativePath ($reason)"
        }
        $fileByPath[$relativePath] = $file.FullName
    }

    [string[]]$relativePaths = @($fileByPath.Keys)
    [System.Array]::Sort($relativePaths, [System.StringComparer]::Ordinal)
    $fixedTimestamp = [System.DateTimeOffset]::new(1980, 1, 1, 0, 0, 0, [System.TimeSpan]::Zero)

    $archiveStream = [System.IO.File]::Open($ArchivePath, [System.IO.FileMode]::CreateNew)
    try {
        $archive = [System.IO.Compression.ZipArchive]::new(
            $archiveStream,
            [System.IO.Compression.ZipArchiveMode]::Create,
            $false
        )
        try {
            foreach ($relativePath in $relativePaths) {
                $entry = $archive.CreateEntry($relativePath, [System.IO.Compression.CompressionLevel]::Optimal)
                $entry.LastWriteTime = $fixedTimestamp
                $input = [System.IO.File]::OpenRead($fileByPath[$relativePath])
                $output = $entry.Open()
                try {
                    $input.CopyTo($output)
                } finally {
                    $output.Dispose()
                    $input.Dispose()
                }
            }
        } finally {
            $archive.Dispose()
        }
    } finally {
        $archiveStream.Dispose()
    }
}

function Remove-StalePackageArtifacts {
    foreach ($entry in @(Get-ChildItem -LiteralPath $OutputDir -Force -ErrorAction SilentlyContinue)) {
        if ($entry.Name -like "flowpilot-*") {
            Write-Host "Removing stale package artifact $($entry.FullName)"
            Remove-PackagePath $entry.FullName
        }
    }
}

function New-EazyFillPackage {
    param([Parameter(Mandatory = $true)][string]$Browser)

    $extensionSourceDir = if ($Browser -eq "firefox") {
        $FirefoxExtensionDir
    } else {
        $ExtensionDir
    }
    $manifestSource = Join-Path $extensionSourceDir "manifest.json"
    $version = Get-ManifestVersion -ManifestPath $manifestSource
    $buildDir = Join-Path $OutputDir "eazyfill-$Browser"
    $archivePath = Join-Path $OutputDir "eazyfill-$Browser-v$version.zip"

    foreach ($oldArchive in @(Get-ChildItem -LiteralPath $OutputDir -Filter "eazyfill-$Browser-v*.zip" -File -ErrorAction SilentlyContinue)) {
        Remove-PackagePath $oldArchive.FullName
    }

    Copy-EazyFillSource -BuildDir $buildDir -ExtensionSourceDir $extensionSourceDir
    New-DeterministicZip -SourceDir $buildDir -ArchivePath $archivePath
    & $AuditScript -PackagePath $archivePath

    Write-Host "Created $archivePath"
    return $archivePath
}

if (!(Test-Path -LiteralPath $AuditScript -PathType Leaf)) {
    throw "Package audit script is missing: $AuditScript"
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
Remove-StalePackageArtifacts

$targets = if ($Target -eq "all") { @("chrome", "firefox") } else { @($Target) }
$packages = @()
foreach ($browser in $targets) {
    $packages += New-EazyFillPackage -Browser $browser
}

Write-Host "EazyFill package output:"
Get-Item -LiteralPath $packages | Select-Object Name, Length, LastWriteTime
