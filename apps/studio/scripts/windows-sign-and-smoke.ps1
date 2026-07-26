param(
  [Parameter(Mandatory = $true)]
  [string]$CertificateThumbprint,
  [Parameter(Mandatory = $true)]
  [string]$TimestampUrl,
  [string]$TargetTriple = "x86_64-pc-windows-msvc",
  [string]$SignTool = "signtool.exe"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Assert-Signed([string]$PathValue) {
  if (-not (Test-Path -LiteralPath $PathValue -PathType Leaf)) {
    throw "Signed output is missing: $PathValue"
  }
  $signature = Get-AuthenticodeSignature -LiteralPath $PathValue
  if ($signature.Status -ne "Valid" -or -not $signature.SignerCertificate) {
    throw "Signature verification failed for ${PathValue}: $($signature.Status)"
  }
  if ($signature.SignerCertificate.Thumbprint -ne $CertificateThumbprint) {
    throw "Unexpected signer certificate for $PathValue"
  }
  return $signature
}

$certificate = Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My |
  Where-Object { $_.Thumbprint -eq $CertificateThumbprint } |
  Select-Object -First 1
if (-not $certificate) {
  throw "A real Windows code-signing certificate with the requested thumbprint was not found."
}
if (-not $certificate.HasPrivateKey) {
  throw "The selected certificate has no private key."
}

$resolvedSignTool = (Get-Command $SignTool -ErrorAction Stop).Source
$sourceSidecar = Join-Path $root "src-tauri\binaries\qbank-sidecar-$TargetTriple.exe"
if (-not (Test-Path -LiteralPath $sourceSidecar -PathType Leaf)) {
  throw "Build the sidecar before signing: $sourceSidecar"
}

# The external sidecar is signed before Tauri copies it into the application bundle.
& $resolvedSignTool sign /fd SHA256 /sha1 $CertificateThumbprint /tr $TimestampUrl /td SHA256 $sourceSidecar
if ($LASTEXITCODE -ne 0) { throw "signtool failed for the sidecar." }
Assert-Signed $sourceSidecar | Out-Null

# Tauri signs the main executable and NSIS installer at their correct build stages.
$override = @{
  bundle = @{
    windows = @{
      certificateThumbprint = $CertificateThumbprint
      digestAlgorithm = "sha256"
      timestampUrl = $TimestampUrl
      tsp = $true
    }
  }
} | ConvertTo-Json -Depth 5 -Compress

Push-Location $root
try {
  & npx tauri build --ci --target $TargetTriple --bundles nsis --config $override
  if ($LASTEXITCODE -ne 0) { throw "Signed Tauri build failed." }
} finally {
  Pop-Location
}

$release = Join-Path $root "src-tauri\target\$TargetTriple\release"
$main = Join-Path $release "qbank-studio.exe"
$sidecar = Join-Path $release "qbank-sidecar.exe"
$installer = Get-ChildItem (Join-Path $release "bundle\nsis") -Filter "*-setup.exe" |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1 -ExpandProperty FullName

foreach ($file in @($sidecar, $main, $installer)) {
  $verified = Assert-Signed $file
  [pscustomobject]@{
    File = $file
    Status = $verified.Status
    Subject = $verified.SignerCertificate.Subject
    Sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash
  }
}

$request = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"1.0","clientVersion":"0.3.0-beta.2"}}'
$response = $request | & $sidecar
if ($LASTEXITCODE -ne 0 -or $response -notmatch '"protocolVersion":"1.0"') {
  throw "Signed sidecar smoke test failed."
}

$process = Start-Process -FilePath $main -PassThru -WindowStyle Hidden
try {
  if (-not $process.WaitForInputIdle(15000)) {
    throw "Signed main executable did not reach an idle window."
  }
} finally {
  if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
}
