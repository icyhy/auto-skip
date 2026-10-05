param(
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$SdkRoot = "$PSScriptRoot\..\.local\android-toolchain",
    [switch]$Check,
    [switch]$DeviceTests,
    [switch]$Install,
    [string]$Serial = ''
)
$ErrorActionPreference = 'Stop'
if (-not $JavaHome) {
    $JavaHome = Get-ChildItem -LiteralPath "$env:USERPROFILE\.jdks" -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath "$($_.FullName)\bin\javac.exe" } | Select-Object -First 1 -ExpandProperty FullName
}
if (-not (Test-Path -LiteralPath "$JavaHome\bin\javac.exe")) { throw '请安装 JDK 17 或更高版本，并通过 -JavaHome 指定位置。' }
$java = "$JavaHome\bin\java.exe"
$javac = "$JavaHome\bin\javac.exe"
$jar = "$JavaHome\bin\jar.exe"
function Run([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program 失败（$LASTEXITCODE）" }
}
function SdkArchive([string]$Name, [string]$Hash, [string]$Destination) {
    $archive = Join-Path $SdkRoot $Name
    if (-not (Test-Path -LiteralPath $archive)) {
        Invoke-WebRequest -Uri "https://dl.google.com/android/repository/$Name" -OutFile $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA1).Hash -ne $Hash) { throw "$Name 校验失败，请重新下载。" }
    Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $SdkRoot $Destination) -Force
}
New-Item -ItemType Directory -Path $SdkRoot -Force | Out-Null
$platform = Join-Path $SdkRoot 'platform\android-35\android.jar'
$tools = Join-Path $SdkRoot 'tools\android-15'
if (-not (Test-Path -LiteralPath $platform)) { SdkArchive 'platform-35_r02.zip' '0bb560a90a7a2cbd0dd8348224d518b638fe7949' 'platform' }
if (-not (Test-Path -LiteralPath "$tools\aapt2.exe")) { SdkArchive 'build-tools_r35_windows.zip' 'af059bb67cf7786f45ee0db85e2d24985df1b4b6' 'tools' }
$work = Join-Path $PSScriptRoot '.local\build'
$out = Join-Path $PSScriptRoot 'dist'
New-Item -ItemType Directory -Path $work,$out,"$work\classes","$work\generated","$work\dex" -Force | Out-Null
if ($Check) {
    New-Item -ItemType Directory -Path "$work\checks" -Force | Out-Null
    Run $javac @('--release','8','-encoding','UTF-8','-d',"$work\checks",
        "$PSScriptRoot\src\com\autoskip\android\Core.java", "$PSScriptRoot\src\com\autoskip\android\FeedParser.java",
        "$PSScriptRoot\tests\CoreCheck.java")
    Run $java @('-ea','-cp',"$work\checks",'com.autoskip.android.CoreCheck')
}
Run "$tools\aapt2.exe" @('compile','--dir',"$PSScriptRoot\res",'-o',"$work\resources.zip")
Run "$tools\aapt2.exe" @('link','-I',$platform,'--manifest',"$PSScriptRoot\AndroidManifest.xml",'--java',"$work\generated",
    '--version-code','3','--version-name','0.1.2','-o',"$work\unsigned.apk", "$work\resources.zip")
$sources = @(Get-ChildItem -LiteralPath "$PSScriptRoot\src","$work\generated" -Filter '*.java' -Recurse | Select-Object -ExpandProperty FullName)
Run $javac (@('--release','8','-encoding','UTF-8','-classpath',$platform,'-d',"$work\classes") + $sources)
Run $jar @('cf',"$work\classes.jar",'-C',"$work\classes",'.')
Run $java @('-cp',"$tools\lib\d8.jar",'com.android.tools.r8.D8','--lib',$platform,'--min-api','26','--output',"$work\dex", "$work\classes.jar")
Run $jar @('uf',"$work\unsigned.apk",'-C',"$work\dex",'classes.dex')
Run "$tools\zipalign.exe" @('-f','-p','4',"$work\unsigned.apk", "$work\aligned.apk")
$key = Join-Path $SdkRoot 'debug.keystore'
if (-not (Test-Path -LiteralPath $key)) {
    Run "$JavaHome\bin\keytool.exe" @('-genkeypair','-keystore',$key,'-storepass','android','-keypass','android','-alias','androiddebugkey',
        '-keyalg','RSA','-keysize','2048','-validity','10000','-dname','CN=Auto Skip Development,O=Auto Skip,C=CN')
}
$apk = Join-Path $out 'AutoSkip-Android-0.1.2.apk'
function Sign([string]$InputApk, [string]$OutputApk) {
    Run $java @('-jar',"$tools\lib\apksigner.jar",'sign','--ks',$key,'--ks-pass','pass:android','--key-pass','pass:android','--out',$OutputApk,$InputApk)
    Run $java @('-jar',"$tools\lib\apksigner.jar",'verify','--verbose',$OutputApk)
}
Sign "$work\aligned.apk" $apk
if ($DeviceTests) {
    New-Item -ItemType Directory -Path "$work\test-classes","$work\test-dex" -Force | Out-Null
    Run $javac @('--release','8','-encoding','UTF-8','-classpath',"$platform;$work\classes",'-d',"$work\test-classes", "$PSScriptRoot\tests\DeviceCheck.java", "$PSScriptRoot\tests\UiRead.java")
    Run $jar @('cf',"$work\test-classes.jar",'-C',"$work\test-classes",'.')
    Run $java @('-cp',"$tools\lib\d8.jar",'com.android.tools.r8.D8','--lib',$platform,'--classpath',"$work\classes.jar",'--min-api','26','--output',"$work\test-dex", "$work\test-classes.jar")
    Run "$tools\aapt2.exe" @('link','-I',$platform,'--manifest',"$PSScriptRoot\tests\AndroidManifest.xml",'-o',"$work\test-unsigned.apk")
    Run $jar @('uf',"$work\test-unsigned.apk",'-C',"$work\test-dex",'classes.dex')
    Run "$tools\zipalign.exe" @('-f','-p','4',"$work\test-unsigned.apk", "$work\test-aligned.apk")
    Sign "$work\test-aligned.apk" (Join-Path $out 'AutoSkip-Android-checks.apk')
}
if ($Install) {
    $deviceArgs = if ($Serial) { @('-s',$Serial) } else { @() }
    Run 'adb' ($deviceArgs + @('install','-r',$apk))
    Run 'adb' ($deviceArgs + @('shell','am','start','-n','com.autoskip.android/.MainActivity'))
}
Write-Output "安装包：$apk"
