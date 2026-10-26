# Dot-source this file to use this project's optional local build/OCR tools.
$docketRoot = Split-Path -Parent $PSScriptRoot
$docketTools = Join-Path $docketRoot '.tools'
$docketJdk = Join-Path $docketTools 'jdk17'
if (!(Test-Path -LiteralPath (Join-Path $docketJdk 'bin\java.exe'))) {
    $docketJdkChild = Get-ChildItem -LiteralPath $docketJdk -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'bin\java.exe') } | Select-Object -First 1
    if ($docketJdkChild) { $docketJdk = $docketJdkChild.FullName }
}
if (Test-Path -LiteralPath (Join-Path $docketJdk 'bin\java.exe')) {
    $env:JAVA_HOME = $docketJdk
    $env:PATH = (Join-Path $docketJdk 'bin') + ';' + $env:PATH
}
$docketSdk = Join-Path $docketTools 'android-sdk'
if (Test-Path -LiteralPath $docketSdk) {
    $env:ANDROID_HOME = $docketSdk
    $env:ANDROID_SDK_ROOT = $docketSdk
    $env:ANDROID_USER_HOME = Join-Path $docketTools 'android-user'
    $env:GRADLE_USER_HOME = Join-Path $docketTools 'gradle'
    $env:PATH = (Join-Path $docketSdk 'platform-tools') + ';' + $env:PATH
}
$docketOcr = Join-Path $docketTools 'ocr\tesseract.exe'
if (Test-Path -LiteralPath $docketOcr) {
    $env:TESSERACT_CMD = $docketOcr
    $env:PATH = (Split-Path -Parent $docketOcr) + ';' + $env:PATH
}
$docketModels = Join-Path $docketTools 'tessdata'
if (Test-Path -LiteralPath $docketModels) { $env:TESSDATA_PREFIX = $docketModels }
