[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SearchTerm,

    [Parameter(Mandatory = $true)]
    [string]$Token,

    [string]$ApiUrl = "http://127.0.0.1:12315/api",

    [string]$PropertyName = "mcp-direct-mutation-test",

    [string]$PropertyValue = "verified-by-mcp-logseq"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-LogseqApi {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Method,

        [Parameter(Mandatory = $true)]
        [object[]]$Arguments
    )

    $requestPath = Join-Path $env:TEMP ("logseq-request-{0}.json" -f [guid]::NewGuid())
    $responsePath = Join-Path $env:TEMP ("logseq-response-{0}.json" -f [guid]::NewGuid())

    try {
        @{ method = $Method; args = $Arguments } |
            ConvertTo-Json -Depth 20 -Compress |
            Set-Content -Path $requestPath -Encoding ascii -NoNewline

        $metrics = & curl.exe -sS -m 20 -o $responsePath -w "%{http_code} %{time_total}" `
            -X POST $ApiUrl `
            -H "Authorization: Bearer $Token" `
            -H "Content-Type: application/json" `
            --data-binary "@$requestPath"

        $metricParts = $metrics -split " "
        $statusCode = [int]$metricParts[0]
        $elapsedSeconds = [double]$metricParts[1]
        $body = if (Test-Path $responsePath) { Get-Content -Path $responsePath -Raw } else { "" }

        if ($statusCode -ne 200) {
            throw "$Method returned HTTP $statusCode in $elapsedSeconds seconds. Response: $body"
        }

        $parsed = if ([string]::IsNullOrWhiteSpace($body) -or $body.Trim() -eq "null") {
            $null
        } else {
            $body | ConvertFrom-Json
        }

        [pscustomobject]@{
            Method = $Method
            ElapsedSeconds = $elapsedSeconds
            Body = $body
            Data = $parsed
        }
    }
    finally {
        Remove-Item -Path $requestPath, $responsePath -Force -ErrorAction SilentlyContinue
    }
}

$targetBlock = $null
$propertyAdded = $false

try {
    Write-Host "Searching for a non-page block containing: $SearchTerm"
    $search = Invoke-LogseqApi -Method "logseq.cli.search" -Arguments @($SearchTerm)
    $targetBlock = @($search.Data.blocks) |
        Where-Object { $_.uuid -and $_.'page?' -ne $true } |
        Select-Object -First 1

    if ($null -eq $targetBlock) {
        throw "No content block found. Use a phrase unique to a scratch block, not a page title."
    }

    $blockUuid = [string]$targetBlock.uuid
    Write-Host "Testing block UUID: $blockUuid"

    $upsert = Invoke-LogseqApi -Method "logseq.Editor.upsertBlockProperty" -Arguments @(
        $blockUuid,
        $PropertyName,
        $PropertyValue
    )
    $propertyAdded = $true
    Write-Host "upsertBlockProperty completed in $($upsert.ElapsedSeconds) seconds."

    $properties = Invoke-LogseqApi -Method "logseq.Editor.getBlockProperties" -Arguments @($blockUuid)
    $actualValue = $properties.Data.$PropertyName
    if ($actualValue -ne $PropertyValue) {
        throw "Read-back failed. Expected '$PropertyValue' for '$PropertyName'; received '$actualValue'."
    }
    Write-Host "Read-back verified: $PropertyName = $actualValue"
}
finally {
    if ($propertyAdded -and $null -ne $targetBlock) {
        $blockUuid = [string]$targetBlock.uuid
        Write-Host "Removing test property from $blockUuid"
        try {
            $remove = Invoke-LogseqApi -Method "logseq.Editor.removeBlockProperty" -Arguments @(
                $blockUuid,
                $PropertyName
            )
            Write-Host "removeBlockProperty completed in $($remove.ElapsedSeconds) seconds."

            $afterRemoval = Invoke-LogseqApi -Method "logseq.Editor.getBlockProperties" -Arguments @($blockUuid)
            if ($null -ne $afterRemoval.Data.$PropertyName) {
                throw "Cleanup read-back failed: '$PropertyName' is still present."
            }
            Write-Host "Cleanup verified. The Editor API still responds after the mutation sequence."
        }
        catch {
            Write-Error "Cleanup failed. Remove '$PropertyName' from block $blockUuid manually. $($_.Exception.Message)"
            throw
        }
    }
}
