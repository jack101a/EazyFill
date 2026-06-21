param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PackageScript = Join-Path $ScriptDir "package_eazyfill_extension.ps1"
$AuditScript = Join-Path $ScriptDir "audit_eazyfill_packages.ps1"
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("eazyfill-package-audit-" + [System.Guid]::NewGuid().ToString("N"))
$FirstOutput = Join-Path $TempRoot "first"
$SecondOutput = Join-Path $TempRoot "second"

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-PackageHashes {
    param([Parameter(Mandatory = $true)][string]$Directory)

    $hashes = @{}
    foreach ($package in @(Get-ChildItem -LiteralPath $Directory -Filter "eazyfill-*.zip" -File)) {
        $hashes[$package.Name] = (Get-FileHash -LiteralPath $package.FullName -Algorithm SHA256).Hash
    }
    return $hashes
}

function New-AuditFixtureZip {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ManifestJson,
        [string]$ExtraEntryName = "",
        [string]$ExtraEntryContent = "test data"
    )

    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew)
    try {
        $archive = [System.IO.Compression.ZipArchive]::new(
            $stream,
            [System.IO.Compression.ZipArchiveMode]::Create,
            $false
        )
        try {
            $fixedTimestamp = [System.DateTimeOffset]::new(1980, 1, 1, 0, 0, 0, [System.TimeSpan]::Zero)
            $entryContent = @{ "manifest.json" = $ManifestJson }
            if (![string]::IsNullOrWhiteSpace($ExtraEntryName)) {
                $entryContent[$ExtraEntryName] = $ExtraEntryContent
            }

            [string[]]$entryNames = @($entryContent.Keys)
            [System.Array]::Sort($entryNames, [System.StringComparer]::Ordinal)
            foreach ($entryName in $entryNames) {
                $entry = $archive.CreateEntry($entryName)
                $entry.LastWriteTime = $fixedTimestamp
                $writer = [System.IO.StreamWriter]::new($entry.Open())
                try {
                    $writer.Write($entryContent[$entryName])
                } finally {
                    $writer.Dispose()
                }
            }
        } finally {
            $archive.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

function Assert-AuditFails {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedMessage
    )

    try {
        & $AuditScript -PackagePath $Path
        throw "Audit unexpectedly accepted fixture: $Path"
    } catch {
        if ($_.Exception.Message -notmatch $ExpectedMessage) {
            throw
        }
    }
}

try {
    New-Item -ItemType Directory -Path $FirstOutput, $SecondOutput -Force | Out-Null

    & $PackageScript -Target all -OutputDir $FirstOutput
    & $PackageScript -Target all -OutputDir $SecondOutput

    $firstHashes = Get-PackageHashes $FirstOutput
    $secondHashes = Get-PackageHashes $SecondOutput
    if ($firstHashes.Count -ne 2 -or $secondHashes.Count -ne 2) {
        throw "Expected exactly two generated browser packages in each test output"
    }

    foreach ($packageName in @($firstHashes.Keys)) {
        if (!$secondHashes.ContainsKey($packageName)) {
            throw "Second build did not produce $packageName"
        }
        if ($firstHashes[$packageName] -cne $secondHashes[$packageName]) {
            throw "Package is not reproducible: $packageName"
        }
    }

    $packages = @(
        Get-ChildItem -LiteralPath $FirstOutput -Filter "eazyfill-*.zip" -File |
            Sort-Object Name |
            ForEach-Object { $_.FullName }
    )
    & $AuditScript -PackagePath $packages

    $negativeDir = Join-Path $TempRoot "negative"
    New-Item -ItemType Directory -Path $negativeDir -Force | Out-Null

    $forbiddenCases = @(
        ".gitkeep",
        "options/options.js.bak",
        ".env",
        "keys/release.pem",
        "fixtures/customer.json",
        "private-data/customer.json",
        "dist/nested.js",
        "node_modules/pkg/index.js",
        "bundle.js.map",
        "background.js",
        "content.js",
        "modules/locator_picker.js",
        "flowpilot-chrome/manifest.json"
    )
    for ($index = 0; $index -lt $forbiddenCases.Count; $index++) {
        $version = "9.8.$index"
        $fixture = Join-Path $negativeDir "eazyfill-chrome-v$version.zip"
        $manifestJson = '{{"manifest_version":3,"name":"EazyFill","version":"{0}"}}' -f $version
        New-AuditFixtureZip -Path $fixture -ManifestJson $manifestJson -ExtraEntryName $forbiddenCases[$index]
        Assert-AuditFails -Path $fixture -ExpectedMessage ("forbidden entry " + [System.Text.RegularExpressions.Regex]::Escape($forbiddenCases[$index]))
    }

    $privateKeyFixture = Join-Path $negativeDir "eazyfill-chrome-v9.9.7.zip"
    New-AuditFixtureZip -Path $privateKeyFixture `
        -ManifestJson '{"manifest_version":3,"name":"EazyFill","version":"9.9.7"}' `
        -ExtraEntryName "assets/data.txt" `
        -ExtraEntryContent "-----BEGIN PRIVATE KEY-----`nnot-a-real-key"
    Assert-AuditFails -Path $privateKeyFixture -ExpectedMessage "embedded private key"

    $missingReferenceFixture = Join-Path $negativeDir "eazyfill-chrome-v9.9.9.zip"
    New-AuditFixtureZip -Path $missingReferenceFixture -ManifestJson '{"manifest_version":3,"name":"EazyFill","version":"9.9.9","background":{"service_worker":"missing.js"}}'
    Assert-AuditFails -Path $missingReferenceFixture -ExpectedMessage "missing package files: missing\.js"

    Write-Host "PASS: Chrome and Firefox packages are deterministic and pass the package audit."
    Write-Host "PASS: Audit rejects all forbidden path families, embedded key data, and missing manifest references."
} finally {
    $fullTempRoot = [System.IO.Path]::GetFullPath($TempRoot)
    $systemTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd("\") + "\"
    if ($fullTempRoot.StartsWith($systemTemp, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $fullTempRoot)) {
        Remove-Item -LiteralPath $fullTempRoot -Recurse -Force
    }
}
