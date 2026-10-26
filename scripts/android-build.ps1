param([string[]]$Tasks = @(':app:assembleDebug', ':app:testDebugUnitTest', ':app:assembleDebugAndroidTest'))
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'tools-env.ps1')
if (!$env:JAVA_HOME -or !(Test-Path -LiteralPath (Join-Path $env:JAVA_HOME 'bin\javac.exe'))) {
    throw 'Set JAVA_HOME to a compatible JDK (17 recommended), or install one under .tools/jdk17.'
}
if (!$env:ANDROID_HOME -or !(Test-Path -LiteralPath (Join-Path $env:ANDROID_HOME 'platforms\android-36\android.jar'))) {
    throw 'Install Android SDK platform 36 and set ANDROID_HOME, or use .tools/android-sdk.'
}
$sdkProperty = $env:ANDROID_HOME.Replace('\', '/').Replace(':', '\:')
Set-Content -LiteralPath (Join-Path $repoRoot 'android\local.properties') -Value "sdk.dir=$sdkProperty" -Encoding ASCII
Push-Location $repoRoot
try {
    & (Join-Path $repoRoot 'android\gradlew.bat') -p android @Tasks --console=plain --no-daemon --max-workers=2
    if ($LASTEXITCODE -ne 0) { throw "Android build failed with code $LASTEXITCODE." }
    $apk = Join-Path $repoRoot 'android\app\build\outputs\apk\debug\app-debug.apk'
    if (($Tasks -contains ':app:assembleDebug') -and (Test-Path -LiteralPath $apk)) {
        $outputDir = Join-Path $repoRoot 'output\android'
        New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
        Copy-Item -LiteralPath $apk -Destination (Join-Path $outputDir 'docket-debug.apk') -Force
        $apkStream = [System.IO.File]::OpenRead($apk)
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        try { $hash = [System.BitConverter]::ToString($sha256.ComputeHash($apkStream)).Replace('-', '').ToLowerInvariant() }
        finally { $apkStream.Dispose(); $sha256.Dispose() }
        Set-Content -LiteralPath (Join-Path $outputDir 'SHA256SUMS.txt') -Value "$hash  docket-debug.apk" -Encoding ASCII
        Write-Host "APK: $outputDir\docket-debug.apk"
    }
} finally { Pop-Location }
