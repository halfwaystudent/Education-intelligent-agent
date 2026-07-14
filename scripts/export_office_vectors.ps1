param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath
)

$ErrorActionPreference = "Stop"
$items = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $items) {
    exit 0
}

$powerPoint = $null
$presentation = $null
$slide = $null

try {
    $powerPoint = New-Object -ComObject PowerPoint.Application
    $presentation = $powerPoint.Presentations.Add()
    $slide = $presentation.Slides.Add(1, 12)

    foreach ($item in $items) {
        $source = [string]$item.source
        $output = [string]$item.output
        if ((-not (Test-Path -LiteralPath $source)) -or (Test-Path -LiteralPath $output)) {
            continue
        }

        $outputDir = Split-Path -Parent $output
        [System.IO.Directory]::CreateDirectory($outputDir) | Out-Null
        $shape = $null
        try {
            # Office renders the vector first; exporting a 2.5x PNG stays sharp after browser downscaling.
            $shape = $slide.Shapes.AddPicture($source, 0, -1, 0, 0, -1, -1)
            $shape.LockAspectRatio = -1
            $shape.Width = $shape.Width * 2.5
            $shape.Export($output, 2)
        }
        catch {
            Write-Warning "Failed to export '$source': $($_.Exception.Message)"
        }
        finally {
            if ($shape) {
                $shape.Delete()
                [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($shape)
            }
        }
    }
}
finally {
    if ($presentation) {
        $presentation.Close()
    }
    if ($powerPoint) {
        $powerPoint.Quit()
    }
    foreach ($comObject in @($slide, $presentation, $powerPoint)) {
        if ($comObject) {
            [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($comObject)
        }
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
