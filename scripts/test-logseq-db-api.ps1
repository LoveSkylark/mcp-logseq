<#
.SYNOPSIS
  Integration harness for a disposable Logseq 2.x DB graph.

.DESCRIPTION
  Core creates one isolated test page and block through logseq.cli.upsertNodes,
  then verifies the native CLI/app read and batch-write paths.

  Direct Editor scenarios intentionally run ONE Editor.* call per invocation.
  Logseq 2.0.1 can wedge its Editor API after a timeout, so restart Logseq and
  start a new PowerShell process before running another Editor scenario.

  The script writes no token to disk. It stores generated page/block UUIDs in
  StatePath so later scenarios can target the same disposable test data.

.EXAMPLE
  .\test-logseq-db-api.ps1 -Suite Core -Token "test-token"

.EXAMPLE
  # Restart Logseq first, then test one direct Editor read.
  .\test-logseq-db-api.ps1 -Suite EditorGetBlockTrue -Token "test-token"

.EXAMPLE
  # This scenario is expected to time out in Logseq 2.0.1.
  .\test-logseq-db-api.ps1 -Suite EditorGetBlockFalse -Token "test-token"

.EXAMPLE
    # Test whether the DB CLI exposes an Editor-equivalent block read.
    .\test-logseq-db-api.ps1 -Suite CliGetBlockTrue -Token "test-token"

.EXAMPLE
  # Execute one custom direct call after Core. Arguments must be a JSON array.
  .\test-logseq-db-api.ps1 -Suite Direct -Token "test-token" `
    -Method "logseq.Editor.getBlockProperties" `
    -ArgumentsJson '["BLOCK_UUID"]'
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Token,

    [ValidateSet(
        "Core",
        "EditorGetBlockTrue",
        "EditorGetBlockFalse",
        "CliGetBlockTrue",
        "CliGetBlockFalse",
        "CliGetBlockProperties",
        "EditorUpsertBlockProperty",
        "EditorGetBlockProperties",
        "EditorRemoveBlockProperty",
        "Direct"
    )]
    [string]$Suite = "Core",

    [string]$ApiUrl = "http://127.0.0.1:12315/api",

    [string]$StatePath = (Join-Path $env:TEMP "mcp-logseq-db-test-state.json"),

    [string]$Method,

    [string]$ArgumentsJson,

    [int]$TimeoutSeconds = 20
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-ObjectValue {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Invoke-LogseqApi {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Arguments
    )

    $requestPath = Join-Path $env:TEMP ("logseq-request-{0}.json" -f [guid]::NewGuid())
    $responsePath = Join-Path $env:TEMP ("logseq-response-{0}.json" -f [guid]::NewGuid())

    try {
        @{ method = $Method; args = $Arguments } |
            ConvertTo-Json -Depth 30 -Compress |
            Set-Content -Path $requestPath -Encoding ascii -NoNewline

        $metrics = & curl.exe -sS -m $TimeoutSeconds -o $responsePath -w "%{http_code} %{time_total}" `
            -X POST $ApiUrl `
            -H "Authorization: Bearer $Token" `
            -H "Content-Type: application/json" `
            --data-binary "@$requestPath"
        $curlExitCode = $LASTEXITCODE
        $metricParts = @($metrics -split " " | Where-Object { $_ })
        $statusCode = if ($metricParts.Count -ge 1) { [int]$metricParts[0] } else { 0 }
        $elapsedSeconds = if ($metricParts.Count -ge 2) { [double]$metricParts[1] } else { 0.0 }
        $body = if (Test-Path $responsePath) { Get-Content -Path $responsePath -Raw } else { "" }

        $parsed = $null
        $parseError = $null
        if (-not [string]::IsNullOrWhiteSpace($body) -and $body.Trim() -ne "null") {
            try {
                $parsed = $body | ConvertFrom-Json
            }
            catch {
                $parseError = $_.Exception.Message
            }
        }

        [pscustomobject]@{
            Method = $Method
            StatusCode = $statusCode
            ElapsedSeconds = $elapsedSeconds
            CurlExitCode = $curlExitCode
            # Some CLI methods (e.g. upsertNodes dry-run) return a plain-text
            # summary instead of JSON on HTTP 200; a parse failure there is
            # not itself an API failure, so success depends only on transport.
            Success = ($statusCode -eq 200 -and $curlExitCode -eq 0)
            Body = $body
            Data = $parsed
            ParseError = $parseError
        }
    }
    finally {
        Remove-Item -Path $requestPath, $responsePath -Force -ErrorAction SilentlyContinue
    }
}

function Add-Result {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.ArrayList]$Results,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Response,
        [bool]$ExpectedSuccess = $true,
        [string]$Notes = ""
    )

    $passed = if ($ExpectedSuccess) { $Response.Success } else { -not $Response.Success }
    [void]$Results.Add([pscustomobject]@{
        Test = $Name
        Passed = $passed
        HTTP = $Response.StatusCode
        Seconds = [math]::Round($Response.ElapsedSeconds, 3)
        Expected = if ($ExpectedSuccess) { "HTTP 200" } else { "failure or timeout" }
        Notes = $Notes
    })

    if (-not $passed) {
        $detail = if ($Response.ParseError) { $Response.ParseError } else { $Response.Body }
        Write-Warning "$Name failed. HTTP $($Response.StatusCode), $($Response.ElapsedSeconds)s. $detail"
    }
}

function Assert-Success {
    param([Parameter(Mandatory = $true)]$Response, [Parameter(Mandatory = $true)][string]$Name)
    if (-not $Response.Success) {
        throw "$Name failed. HTTP $($Response.StatusCode) in $($Response.ElapsedSeconds)s. $($Response.Body)"
    }
}

function Find-Block {
    param([AllowNull()]$Blocks, [Parameter(Mandatory = $true)][string]$Marker)

    if ($null -eq $Blocks) { return $null }

    foreach ($block in @($Blocks)) {
        if ($null -eq $block) { continue }
        # Live getPageData returns bare `title`/`uuid`, not namespaced block/title.
        $title = [string](Get-ObjectValue -Object $block -Name "title")
        if ([string]::IsNullOrWhiteSpace($title)) {
            $title = [string](Get-ObjectValue -Object $block -Name "block/title")
        }
        if ([string]::IsNullOrWhiteSpace($title)) {
            $title = [string](Get-ObjectValue -Object $block -Name "content")
        }
        if ($title -like "*$Marker*") { return $block }

        $children = Get-ObjectValue -Object $block -Name "block/children"
        if ($null -eq $children) { $children = Get-ObjectValue -Object $block -Name "children" }
        $found = Find-Block -Blocks $children -Marker $Marker
        if ($null -ne $found) { return $found }
    }
    return $null
}

function Get-State {
    if (-not (Test-Path $StatePath)) {
        throw "State file not found: $StatePath. Run -Suite Core first."
    }
    return (Get-Content -Path $StatePath -Raw | ConvertFrom-Json)
}

function Save-State {
    param([Parameter(Mandatory = $true)]$State)
    $State | ConvertTo-Json -Depth 10 | Set-Content -Path $StatePath -Encoding utf8
    Write-Host "Saved test state to $StatePath"
}

function Invoke-CoreSuite {
    $results = [System.Collections.ArrayList]::new()
    $runId = [guid]::NewGuid().ToString("N").Substring(0, 12)
    $pageTitle = "MCP DB API Test $runId"
    $marker = "mcp-db-api-marker-$runId"
    $temporaryPageId = "temp-page-$runId"

    $dbCheck = Invoke-LogseqApi -Method "logseq.App.checkCurrentIsDbGraph" -Arguments @()
    Add-Result -Results $results -Name "DB graph detection" -Response $dbCheck
    if ($dbCheck.Success -and $dbCheck.Data -ne $true) {
        throw "The active graph is not a DB graph. Open an empty DB graph and retry."
    }

    foreach ($readMethod in @(
        @{ Name = "List pages"; Method = "logseq.cli.listPages"; Arguments = @(@{ expand = $false }) },
        @{ Name = "List tags"; Method = "logseq.cli.listTags"; Arguments = @(@{ expand = $false }) },
        @{ Name = "List properties"; Method = "logseq.cli.listProperties"; Arguments = @(@{ expand = $false }) }
    )) {
        $response = Invoke-LogseqApi -Method $readMethod.Method -Arguments $readMethod.Arguments
        Add-Result -Results $results -Name $readMethod.Name -Response $response
    }

    $operations = @(
        @{ operation = "add"; entityType = "page"; id = $temporaryPageId; data = @{ title = $pageTitle } },
        @{ operation = "add"; entityType = "block"; data = @{ "page-id" = $temporaryPageId; title = $marker } }
    )

    $dryRunArguments = [System.Collections.ArrayList]::new()
    [void]$dryRunArguments.Add($operations)
    [void]$dryRunArguments.Add(@{ "dry-run" = $true })
    $dryRun = Invoke-LogseqApi -Method "logseq.cli.upsertNodes" -Arguments $dryRunArguments.ToArray()
    Add-Result -Results $results -Name "upsertNodes dry run" -Response $dryRun
    Assert-Success -Response $dryRun -Name "upsertNodes dry run"

    $commitArguments = [System.Collections.ArrayList]::new()
    [void]$commitArguments.Add($operations)
    [void]$commitArguments.Add(@{ "dry-run" = $false })
    $commit = Invoke-LogseqApi -Method "logseq.cli.upsertNodes" -Arguments $commitArguments.ToArray()
    Add-Result -Results $results -Name "upsertNodes commit" -Response $commit
    Assert-Success -Response $commit -Name "upsertNodes commit"

    $pageData = Invoke-LogseqApi -Method "logseq.cli.getPageData" -Arguments @($pageTitle)
    Add-Result -Results $results -Name "Get seeded page data" -Response $pageData
    Assert-Success -Response $pageData -Name "Get seeded page data"

    $entity = Get-ObjectValue -Object $pageData.Data -Name "entity"
    $pageUuid = [string](Get-ObjectValue -Object $entity -Name "block/uuid")
    if ([string]::IsNullOrWhiteSpace($pageUuid)) { $pageUuid = [string](Get-ObjectValue -Object $entity -Name "uuid") }
    $block = Find-Block -Blocks (Get-ObjectValue -Object $pageData.Data -Name "blocks") -Marker $marker
    if ($null -eq $block) { throw "The seeded block was not found in getPageData." }
    $blockUuid = [string](Get-ObjectValue -Object $block -Name "block/uuid")
    if ([string]::IsNullOrWhiteSpace($blockUuid)) { $blockUuid = [string](Get-ObjectValue -Object $block -Name "uuid") }
    if ([string]::IsNullOrWhiteSpace($blockUuid)) { throw "The seeded block has no UUID." }

    $cliSearch = Invoke-LogseqApi -Method "logseq.cli.search" -Arguments @($marker)
    Add-Result -Results $results -Name "CLI search seeded block" -Response $cliSearch

    $appSearch = Invoke-LogseqApi -Method "logseq.app.search" -Arguments @($marker, @{ "enable-snippet?" = $false })
    Add-Result -Results $results -Name "App search seeded block" -Response $appSearch

    Save-State -State ([pscustomobject]@{
        RunId = $runId
        PageTitle = $pageTitle
        PageUuid = $pageUuid
        BlockUuid = $blockUuid
        Marker = $marker
        CreatedAt = (Get-Date).ToUniversalTime().ToString("o")
    })

    Write-Host ""
    Write-Host "Core suite finished. Leave the generated page in this disposable graph."
    Write-Host "Restart Logseq before every Editor* suite."
    return $results
}

function Invoke-EditorScenario {
    param([Parameter(Mandatory = $true)]$State)
    $results = [System.Collections.ArrayList]::new()
    $blockUuid = [string]$State.BlockUuid

    switch ($Suite) {
        "EditorGetBlockTrue" {
            $response = Invoke-LogseqApi -Method "logseq.Editor.getBlock" -Arguments @($blockUuid, @{ includeChildren = $true })
            Add-Result -Results $results -Name "Editor.getBlock includeChildren=true" -Response $response
        }
        "EditorGetBlockFalse" {
            $response = Invoke-LogseqApi -Method "logseq.Editor.getBlock" -Arguments @($blockUuid, @{ includeChildren = $false })
            Add-Result -Results $results -Name "Editor.getBlock includeChildren=false" -Response $response -ExpectedSuccess $false -Notes "Known Logseq 2.0.1 hang candidate"
        }
        "CliGetBlockTrue" {
            $response = Invoke-LogseqApi -Method "logseq.cli.getBlock" -Arguments @($blockUuid, @{ includeChildren = $true })
            Add-Result -Results $results -Name "CLI.getBlock includeChildren=true" -Response $response -Notes "Candidate DB mapping; compare result shape with Editor.getBlock"
        }
        "CliGetBlockFalse" {
            $response = Invoke-LogseqApi -Method "logseq.cli.getBlock" -Arguments @($blockUuid, @{ includeChildren = $false })
            Add-Result -Results $results -Name "CLI.getBlock includeChildren=false" -Response $response -ExpectedSuccess $false -Notes "Candidate mapping with known unsafe argument shape"
        }
        "CliGetBlockProperties" {
            $response = Invoke-LogseqApi -Method "logseq.cli.getBlockProperties" -Arguments @($blockUuid)
            Add-Result -Results $results -Name "CLI.getBlockProperties" -Response $response -Notes "Candidate DB mapping; use one scenario per Logseq session"
        }
        "EditorUpsertBlockProperty" {
            $response = Invoke-LogseqApi -Method "logseq.Editor.upsertBlockProperty" -Arguments @($blockUuid, "mcp-direct-mutation-test", "run-$($State.RunId)")
            Add-Result -Results $results -Name "Editor.upsertBlockProperty" -Response $response -Notes "Do not issue a second Editor call in this session"
        }
        "EditorGetBlockProperties" {
            $response = Invoke-LogseqApi -Method "logseq.Editor.getBlockProperties" -Arguments @($blockUuid)
            Add-Result -Results $results -Name "Editor.getBlockProperties" -Response $response
        }
        "EditorRemoveBlockProperty" {
            $response = Invoke-LogseqApi -Method "logseq.Editor.removeBlockProperty" -Arguments @($blockUuid, "mcp-direct-mutation-test")
            Add-Result -Results $results -Name "Editor.removeBlockProperty" -Response $response -Notes "Use after a separate successful property-add test"
        }
        "Direct" {
            if ([string]::IsNullOrWhiteSpace($Method) -or [string]::IsNullOrWhiteSpace($ArgumentsJson)) {
                throw "-Suite Direct requires -Method and -ArgumentsJson."
            }
            $arguments = @($ArgumentsJson | ConvertFrom-Json)
            $response = Invoke-LogseqApi -Method $Method -Arguments $arguments
            Add-Result -Results $results -Name $Method -Response $response
        }
    }

    return $results
}

$results = if ($Suite -eq "Core") {
    Invoke-CoreSuite
} else {
    Invoke-EditorScenario -State (Get-State)
}

Write-Host ""
$results | Format-Table -AutoSize

if (@($results | Where-Object { -not $_.Passed }).Count -gt 0) {
    Write-Warning "One or more tests failed. Record the table, inspect the graph through CLI/app reads, then restart Logseq before another Editor scenario."
    exit 1
}

Write-Host "All selected tests passed."
exit 0
