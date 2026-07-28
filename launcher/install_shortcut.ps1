# 在 D:\Desktop 创建启动 SJTUClaw 的快捷方式
#
# 解释器必须取本机盘符上的 pythonw.exe，不能用项目 venv：
# 从 \\wsl.localhost 直接启动 exe 会触发 Windows 网络区域的"打开文件-安全警告"
# 弹窗，双击时该弹窗常被遮挡，表现为点了没反应。脚本本身放 UNC 上是安全的
# （只是被读取，不是被执行）。
#
# 不经过 .bat：cmd 不接受 UNC 当前目录，pushd 在 \\wsl.localhost 上也不映射盘符。
# WorkingDirectory 留空——start_gateway.py 用 __file__ 定位 ROOT。

$ErrorActionPreference = 'Stop'

$bs      = [char]92
$project = '{0}{0}wsl.localhost{0}Ubuntu{0}home{0}darling{0}SJTU-claw' -f $bs
$boot    = Join-Path $project 'launcher\start_gateway.py'
$icon    = Join-Path $project 'launcher\sjtuclaw.ico'
$link    = 'D:\Desktop\SJTUClaw.lnk'

foreach ($p in @($boot, $icon)) {
    if (-not (Test-Path -LiteralPath $p)) { throw "找不到：$p" }
}

# 找一个本机的 pythonw.exe，且 requests / python-dotenv 可用。
# 依赖检查要用同目录的 python.exe：pythonw 无控制台，PowerShell 取不到它的退出码。
$candidates = @()
$candidates += 'D:\Anaconda3\pythonw.exe'
$candidates += "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\pythonw.exe"
$candidates += (Get-Command pythonw.exe -All -EA SilentlyContinue | ForEach-Object { $_.Source })

$pyw = $null
foreach ($c in $candidates) {
    if (-not $c -or $c.StartsWith($bs + $bs)) { continue }   # 排除 UNC
    if (-not (Test-Path -LiteralPath $c)) { continue }
    # WindowsApps 下是 0 字节的应用执行别名存根，不能直接用
    if ((Get-Item -LiteralPath $c).Length -eq 0) { continue }

    $console = Join-Path (Split-Path $c -Parent) 'python.exe'
    if (-not (Test-Path -LiteralPath $console)) { continue }
    & $console -c "import requests, dotenv" 2>$null
    if ($LASTEXITCODE -eq 0) { $pyw = $c; break }
}
if (-not $pyw) { throw "未找到本机可用的 pythonw.exe（需已安装 requests / python-dotenv）" }

# 图标复制到本机盘符再引用：Explorer 对 UNC 路径上的 .ico 渲染不可靠，
# 直接指向 \\wsl.localhost 会退化成默认图标。源文件仍留在项目里。
$localIcon = Join-Path $env:LOCALAPPDATA 'SJTUClaw\sjtuclaw.ico'
New-Item -ItemType Directory -Force -Path (Split-Path $localIcon -Parent) | Out-Null
Copy-Item -LiteralPath $icon -Destination $localIcon -Force

$sc = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
$sc.TargetPath       = $pyw
$sc.Arguments        = '"{0}"' -f $boot
$sc.IconLocation     = "$localIcon,0"
$sc.Description      = 'SJTUClaw — 启动 Gateway 并打开界面'
$sc.Save()

Write-Output "已创建：$link"
Write-Output "  解释器：$pyw"
Write-Output "  启动脚本：$boot"
Write-Output "  图标：$localIcon"
