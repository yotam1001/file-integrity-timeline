Add-Type -AssemblyName System.Drawing

$target = Join-Path (Split-Path $PSScriptRoot -Parent) 'docs\social-card.png'
$bitmap = [System.Drawing.Bitmap]::new(1200, 630)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$dark = [System.Drawing.Color]::FromArgb(18, 61, 49)
$lime = [System.Drawing.Color]::FromArgb(212, 240, 137)
$pale = [System.Drawing.Color]::FromArgb(217, 229, 220)
$ring = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(70, 139, 109), 2)
$titleFont = [System.Drawing.Font]::new('Segoe UI', 62, [System.Drawing.FontStyle]::Bold)
$smallFont = [System.Drawing.Font]::new('Segoe UI', 22, [System.Drawing.FontStyle]::Regular)
$brandFont = [System.Drawing.Font]::new('Segoe UI', 20, [System.Drawing.FontStyle]::Bold)
$limeBrush = [System.Drawing.SolidBrush]::new($lime)
$whiteBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
$paleBrush = [System.Drawing.SolidBrush]::new($pale)
try {
    $graphics.Clear($dark)
    $graphics.DrawEllipse($ring, 800, -230, 540, 540)
    $graphics.DrawEllipse($ring, 720, -310, 700, 700)
    $graphics.DrawEllipse($ring, 640, -390, 860, 860)
    $graphics.DrawString('FileIntegrityTimeline', $brandFont, $limeBrush, 66, 54)
    $graphics.DrawString('Know when your', $titleFont, $whiteBrush, 62, 184)
    $graphics.DrawString('files changed.', $titleFont, $whiteBrush, 62, 278)
    $graphics.DrawString('Dated SHA-256 baselines for the folders you care about.', $smallFont, $paleBrush, 67, 440)
    $graphics.DrawString('Free  |  Read only  |  Windows GUI + CLI', $smallFont, $limeBrush, 67, 507)
    $bitmap.Save($target, [System.Drawing.Imaging.ImageFormat]::Png)
} finally {
    $graphics.Dispose()
    $bitmap.Dispose()
    $ring.Dispose()
    $titleFont.Dispose()
    $smallFont.Dispose()
    $brandFont.Dispose()
    $limeBrush.Dispose()
    $whiteBrush.Dispose()
    $paleBrush.Dispose()
}
Write-Output $target
