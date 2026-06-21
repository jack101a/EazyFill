param(
    [Parameter(Mandatory = $true, ValueFromPipeline = $true)]
    [string[]]$PackagePath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-ObjectProperty {
    param(
        [object]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Get-NestedProperty {
    param(
        [object]$Object,
        [Parameter(Mandatory = $true)][string[]]$Names
    )

    $value = $Object
    foreach ($name in $Names) {
        $value = Get-ObjectProperty -Object $value -Name $name
        if ($null -eq $value) {
            return $null
        }
    }
    return $value
}

function Add-Reference {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[string]]$References,
        [object]$Value
    )

    if ($null -eq $Value) {
        return
    }
    if ($Value -is [string]) {
        if (![string]::IsNullOrWhiteSpace($Value)) {
            $References.Add($Value)
        }
        return
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        foreach ($item in $Value) {
            Add-Reference -References $References -Value $item
        }
    }
}

function Add-PropertyValues {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[string]]$References,
        [object]$Object
    )

    if ($null -eq $Object -or $null -eq $Object.PSObject) {
        return
    }
    foreach ($property in @($Object.PSObject.Properties)) {
        Add-Reference -References $References -Value $property.Value
    }
}

function Get-ManifestReferences {
    param([Parameter(Mandatory = $true)][object]$Manifest)

    $references = [System.Collections.Generic.List[string]]::new()

    $defaultLocale = Get-ObjectProperty $Manifest "default_locale"
    if ($defaultLocale) {
        $references.Add("_locales/$defaultLocale/messages.json")
    }

    Add-Reference $references (Get-NestedProperty $Manifest @("background", "service_worker"))
    Add-Reference $references (Get-NestedProperty $Manifest @("background", "scripts"))
    Add-Reference $references (Get-NestedProperty $Manifest @("action", "default_popup"))
    Add-PropertyValues $references (Get-NestedProperty $Manifest @("action", "default_icon"))
    Add-Reference $references (Get-NestedProperty $Manifest @("browser_action", "default_popup"))
    Add-PropertyValues $references (Get-NestedProperty $Manifest @("browser_action", "default_icon"))
    Add-Reference $references (Get-NestedProperty $Manifest @("page_action", "default_popup"))
    Add-PropertyValues $references (Get-NestedProperty $Manifest @("page_action", "default_icon"))
    Add-Reference $references (Get-ObjectProperty $Manifest "options_page")
    Add-Reference $references (Get-NestedProperty $Manifest @("options_ui", "page"))
    Add-Reference $references (Get-ObjectProperty $Manifest "devtools_page")
    Add-Reference $references (Get-NestedProperty $Manifest @("sidebar_action", "default_panel"))
    Add-PropertyValues $references (Get-NestedProperty $Manifest @("sidebar_action", "default_icon"))
    Add-PropertyValues $references (Get-ObjectProperty $Manifest "icons")
    Add-PropertyValues $references (Get-ObjectProperty $Manifest "chrome_url_overrides")

    foreach ($contentScript in @((Get-ObjectProperty $Manifest "content_scripts"))) {
        Add-Reference $references (Get-ObjectProperty $contentScript "js")
        Add-Reference $references (Get-ObjectProperty $contentScript "css")
    }
    foreach ($resourceBlock in @((Get-ObjectProperty $Manifest "web_accessible_resources"))) {
        if ($resourceBlock -is [string]) {
            Add-Reference $references $resourceBlock
        } else {
            Add-Reference $references (Get-ObjectProperty $resourceBlock "resources")
        }
    }
    foreach ($ruleResource in @((Get-NestedProperty $Manifest @("declarative_net_request", "rule_resources")))) {
        Add-Reference $references (Get-ObjectProperty $ruleResource "path")
    }
    Add-Reference $references (Get-NestedProperty $Manifest @("sandbox", "pages"))

    [string[]]$result = @($references | Select-Object -Unique)
    [System.Array]::Sort($result, [System.StringComparer]::Ordinal)
    return $result
}

function Get-PackageBlockReason {
    param([Parameter(Mandatory = $true)][string]$EntryName)

    $path = $EntryName.Replace("\", "/").TrimStart("/")
    $segments = @($path.Split("/") | Where-Object { $_.Length -gt 0 })
    $leaf = if ($segments.Count -gt 0) { $segments[-1] } else { "" }
    $extension = [System.IO.Path]::GetExtension($leaf).ToLowerInvariant()

    if ($EntryName.Contains("\") -or $EntryName.StartsWith("/") -or $EntryName -match "^[A-Za-z]:" -or $path -match "(^|/)\.\.(/|$)") {
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

function Test-SensitiveEntryContent {
    param([Parameter(Mandatory = $true)][System.IO.Compression.ZipArchiveEntry]$Entry)

    $stream = $Entry.Open()
    try {
        $length = [System.Math]::Min(16384, [int]$Entry.Length)
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

function Test-ReferenceExists {
    param(
        [Parameter(Mandatory = $true)][string]$Reference,
        [Parameter(Mandatory = $true)][string[]]$EntryNames
    )

    $normalized = $Reference.Replace("\", "/")
    if (
        [string]::IsNullOrWhiteSpace($normalized) -or
        $normalized.StartsWith("/") -or
        $normalized -match "^[A-Za-z][A-Za-z0-9+.-]*:" -or
        $normalized -match "(^|/)\.\.(/|$)"
    ) {
        throw "Manifest contains unsafe or external file reference: $Reference"
    }

    if ($normalized.IndexOfAny([char[]]"*?[") -ge 0) {
        $pattern = [System.Management.Automation.WildcardPattern]::new(
            $normalized,
            [System.Management.Automation.WildcardOptions]::None
        )
        return @($EntryNames | Where-Object { $pattern.IsMatch($_) }).Count -gt 0
    }
    return $EntryNames -ccontains $normalized
}

function Read-ZipEntryText {
    param([Parameter(Mandatory = $true)][System.IO.Compression.ZipArchiveEntry]$Entry)

    $stream = $Entry.Open()
    $reader = [System.IO.StreamReader]::new($stream)
    try {
        return $reader.ReadToEnd()
    } finally {
        $reader.Dispose()
        $stream.Dispose()
    }
}

function Test-EazyFillPackage {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (!(Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "Package not found: $fullPath"
    }

    $fileName = [System.IO.Path]::GetFileName($fullPath)
    $match = [System.Text.RegularExpressions.Regex]::Match(
        $fileName,
        "^eazyfill-(chrome|firefox)-v([0-9]+(?:\.[0-9]+){2,3})\.zip$",
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )
    if (!$match.Success) {
        throw "Package filename must match eazyfill-<browser>-v<version>.zip: $fileName"
    }
    $browser = $match.Groups[1].Value.ToLowerInvariant()
    $fileVersion = $match.Groups[2].Value

    $archive = [System.IO.Compression.ZipFile]::OpenRead($fullPath)
    try {
        $entries = @($archive.Entries)
        if ($entries.Count -eq 0) {
            throw "Package is empty: $fileName"
        }

        [string[]]$entryNames = @($entries | ForEach-Object { $_.FullName })
        [string[]]$sortedNames = @($entryNames)
        [System.Array]::Sort($sortedNames, [System.StringComparer]::Ordinal)
        for ($index = 0; $index -lt $entryNames.Count; $index++) {
            if ($entryNames[$index] -cne $sortedNames[$index]) {
                throw "ZIP entries are not in deterministic ordinal order at index $index"
            }
        }

        $seenNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        foreach ($entry in $entries) {
            if (!$seenNames.Add($entry.FullName)) {
                throw "Package contains duplicate entry name: $($entry.FullName)"
            }
            if ($entry.FullName.EndsWith("/")) {
                throw "Package contains an unnecessary directory entry: $($entry.FullName)"
            }
            $reason = Get-PackageBlockReason $entry.FullName
            if ($reason) {
                throw "Package contains forbidden entry $($entry.FullName) ($reason)"
            }
            if (Test-SensitiveEntryContent $entry) {
                throw "Package contains embedded private key or certificate data: $($entry.FullName)"
            }
            $timestamp = $entry.LastWriteTime
            if (
                $timestamp.Year -ne 1980 -or
                $timestamp.Month -ne 1 -or
                $timestamp.Day -ne 1 -or
                $timestamp.Hour -ne 0 -or
                $timestamp.Minute -ne 0 -or
                $timestamp.Second -ne 0
            ) {
                throw "ZIP entry has non-deterministic timestamp: $($entry.FullName) = $timestamp"
            }
        }

        $manifestEntries = @($entries | Where-Object { $_.FullName -ceq "manifest.json" })
        if ($manifestEntries.Count -ne 1) {
            throw "Package must contain exactly one root manifest.json"
        }
        $manifest = (Read-ZipEntryText $manifestEntries[0]) | ConvertFrom-Json
        $manifestName = [string](Get-ObjectProperty $manifest "name")
        $manifestVersion = [string](Get-ObjectProperty $manifest "version")
        if ($manifestName -cne "EazyFill") {
            throw "Manifest name must be EazyFill, found: $manifestName"
        }
        if ($manifestVersion -cne $fileVersion) {
            throw "Manifest version $manifestVersion does not match package filename version $fileVersion"
        }
        if ($browser -eq "firefox" -and !(Get-NestedProperty $manifest @("browser_specific_settings", "gecko", "id"))) {
            throw "Firefox package manifest is missing browser_specific_settings.gecko.id"
        }

        $missing = [System.Collections.Generic.List[string]]::new()
        $references = @(Get-ManifestReferences $manifest)
        foreach ($reference in $references) {
            if (!(Test-ReferenceExists -Reference $reference -EntryNames $entryNames)) {
                $missing.Add($reference)
            }
        }
        if ($missing.Count -gt 0) {
            throw "Manifest references missing package files: $($missing -join ', ')"
        }
    } finally {
        $archive.Dispose()
    }

    $hash = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
    [pscustomobject]@{
        Package = $fileName
        Browser = $browser
        Version = $fileVersion
        Entries = $entryNames.Count
        ManifestReferences = $references.Count
        Sha256 = $hash
    }
}

$results = foreach ($path in $PackagePath) {
    Test-EazyFillPackage -Path $path
}

$results | Sort-Object Browser | Format-Table -AutoSize | Out-Host
