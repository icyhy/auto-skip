param([string]$Python = "$PSScriptRoot\.venv\Scripts\python.exe")
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath $Python)) { throw '请先创建 .venv 并安装 requirements.txt 和 pyinstaller==6.19.0' }
& $Python build_bundle.py
if ($LASTEXITCODE -ne 0) { throw '桌面程序打包失败' }
& $Python build_bundle.py --bridge
if ($LASTEXITCODE -ne 0) { throw '本地连接程序打包失败' }
$bridgeFolder = "$PSScriptRoot\dist\AutoSkip\bridge"
New-Item -ItemType Directory -Path $bridgeFolder -Force | Out-Null
Copy-Item -Path "$PSScriptRoot\dist\AutoSkipBridge\*" -Destination $bridgeFolder -Recurse -Force
Copy-Item -LiteralPath "$PSScriptRoot\extension" -Destination "$PSScriptRoot\dist\AutoSkip" -Recurse -Force
Copy-Item -LiteralPath "$PSScriptRoot\README.md" -Destination "$PSScriptRoot\dist\AutoSkip\README.md" -Force
Copy-Item -LiteralPath "$PSScriptRoot\VALIDATION.md" -Destination "$PSScriptRoot\dist\AutoSkip\VALIDATION.md" -Force
Copy-Item -LiteralPath "$PSScriptRoot\THIRD_PARTY_NOTICES.md" -Destination "$PSScriptRoot\dist\AutoSkip\THIRD_PARTY_NOTICES.md" -Force
Write-Output "完成：$PSScriptRoot\dist\AutoSkip\AutoSkip.exe"
