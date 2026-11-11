# StemDeck dev server (Windows, GPU). Two shortcuts start it:
#   "Iniciar StemDeck dev.cmd"                  -> this PC only (http://localhost:8001)
#   "Compartir StemDeck en la red.cmd" (-Lan)   -> also a phone or tablet on the same Wi-Fi
#
#  1. If a server already answers on the port, just opens the browser. With
#     -Lan and a server that is not shared, asks before restarting it shared.
#  2. Warns when the venv's torch has no CUDA (a `uv run`/`uv sync` swaps the
#     CUDA build for the CPU one; docs/partitura.md has the reinstall line).
#  3. Starts uvicorn with the Proactor loop and no --reload (docs/partitura.md,
#     "Modo dev en Windows"), and in the background, once it answers:
#     - points the YouTube cookies setting at youtube-cookies.txt in the repo
#       root when that file exists (and clears it when the file is gone);
#     - opens the browser (with -Lan, also a QR code of the tablet's address).
#  4. -Lan: a second listener serves the same app over https, as the desktop
#     app does: StemDeck refuses plain http from other devices (transpose needs
#     a secure context). The certificate is a self-signed one for this PC's LAN
#     addresses, made with Git's openssl into .run/certs/ and remade when the
#     addresses change; the tablet's browser warns once. Port: the first free
#     one from 8443 (a mitmproxy held 8443 here). This PC keeps plain http on
#     127.0.0.1:8001. The Windows firewall still decides who gets in
#     (docs/partitura.md, "Desde el celular o la tablet").
param([switch]$Lan)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root
$port = 8001
$url = "http://localhost:$port"
$python = Join-Path $root '.venv\Scripts\python.exe'
$uvicorn = Join-Path $root '.venv\Scripts\uvicorn.exe'
$cookies = Join-Path $root 'youtube-cookies.txt'
# API calls go to 127.0.0.1: "localhost" can resolve to ::1 first, which the
# server (bound to 127.0.0.1) never answers. The browser still opens localhost.
$api = "http://127.0.0.1:$port"

$Host.UI.RawUI.WindowTitle = if ($Lan) { "StemDeck dev (compartido en la red) - $url" } else { "StemDeck dev - $url" }

if (-not (Test-Path $uvicorn)) {
    Write-Host "No encuentro $uvicorn. Crea el entorno con: uv sync --extra dev" -ForegroundColor Red
    exit 1
}

# The address a tablet uses: this PC's private address on the network with a
# gateway (the Wi-Fi), not a virtual adapter's.
function TabletIp {
    $ips = @(Get-NetIPConfiguration -ErrorAction SilentlyContinue | Where-Object { $_.IPv4DefaultGateway } |
        ForEach-Object { $_.IPv4Address.IPAddress })
    $private = $ips | Where-Object { $_ -match '^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)' } | Select-Object -First 1
    if ($private) { return $private }
    return ($ips | Select-Object -First 1)
}

function ShowShared($httpsAddr) {
    Write-Host "Compartido en la red. En el celular o la tablet (misma Wi-Fi) abre:" -ForegroundColor Cyan
    Write-Host "  $httpsAddr/mobile/      (partituras: $httpsAddr/score/)" -ForegroundColor Cyan
    Write-Host "  La primera vez el navegador avisa que el certificado no es de confianza: Avanzado -> Continuar." -ForegroundColor DarkCyan
    $public = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue | Where-Object { $_.NetworkCategory -eq 'Public' })
    if ($public.Count) {
        Write-Host ("AVISO: la red '" + $public[0].Name + "' es Publica: si la tablet no conecta, ver docs/partitura.md.") -ForegroundColor Yellow
    }
}

$running = $false
try { Invoke-RestMethod "$api/api/health" -TimeoutSec 2 | Out-Null; $running = $true } catch { }
if ($running) {
    if (-not $Lan) {
        Write-Host "StemDeck ya esta corriendo en $url; abro el navegador." -ForegroundColor Green
        Start-Process $url
        exit 0
    }
    $shared = @((Invoke-RestMethod "$api/api/settings" -TimeoutSec 10).lan_addresses | Where-Object { $_ -like 'https://*' })
    if ($shared.Count) {
        $addr = ($shared | Where-Object { $_ -like "https://$(TabletIp):*" } | Select-Object -First 1)
        if (-not $addr) { $addr = $shared[0] }
        ShowShared $addr
        Start-Process $url
        Start-Process "$url/api/qr?url=$([uri]::EscapeDataString("$addr/mobile/"))"
        Write-Host "Ya estaba compartido; abri la app y el codigo QR. Puedes cerrar esta ventana." -ForegroundColor Green
        Read-Host "Enter para cerrar" | Out-Null
        exit 0
    }
    # Running for this PC only: sharing needs a restart (the https listener
    # lives in the same process).
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    $proc = if ($conn) { Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" } else { $null }
    if (-not $proc -or $proc.CommandLine -notmatch 'app\.main:app') {
        Write-Host "El puerto $port lo usa otro programa; no lo toco." -ForegroundColor Red
        Read-Host "Enter para cerrar" | Out-Null
        exit 1
    }
    Write-Host "StemDeck ya esta abierto, pero solo para este PC." -ForegroundColor Yellow
    $answer = Read-Host "Reiniciarlo compartido en la red? Se corta lo que este sonando o procesando (S/N)"
    if ($answer -notmatch '^[sSyY]') { exit 0 }
    Stop-Process -Id $proc.ProcessId -Force
    for ($i = 0; $i -lt 30 -and (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 300 }
}

& $python -c "import sys, torch; sys.exit(0 if torch.cuda.is_available() else 1)" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "GPU: CUDA disponible (separacion y partitura en GPU)." -ForegroundColor Green
} else {
    Write-Host "AVISO: este entorno tiene torch SIN CUDA; todo correra en CPU (mas lento)." -ForegroundColor Yellow
    Write-Host "Para volver a la GPU, cierra esto y ejecuta (ver docs/partitura.md):" -ForegroundColor Yellow
    Write-Host "  uv pip install --python .venv/Scripts/python.exe --no-deps torch==2.8.0+cu128 torchaudio==2.8.0+cu128 torchvision==0.23.0+cu128 --index-url https://download.pytorch.org/whl/cu128"
}

if (Test-Path $cookies) {
    Write-Host "Cookies de YouTube: se usaran desde youtube-cookies.txt (solo si YouTube bloquea la descarga)." -ForegroundColor Green
} else {
    Write-Host "Cookies de YouTube: no hay youtube-cookies.txt en $root (opcional; ver docs/partitura.md)."
}

# -Lan: https for other devices, with a self-signed certificate for this PC's addresses.
$qr = ''
Remove-Item Env:STEMDECK_HTTPS_PORT, Env:STEMDECK_SSL_CERT, Env:STEMDECK_SSL_KEY -ErrorAction SilentlyContinue
if ($Lan) {
    $lanIps = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
        Select-Object -ExpandProperty IPAddress | Sort-Object)
    $httpsPort = 8443
    while (Get-NetTCPConnection -LocalPort $httpsPort -State Listen -ErrorAction SilentlyContinue) { $httpsPort++ }
    $certDir = Join-Path $root '.run\certs'
    $crt = Join-Path $certDir 'dev-lan.crt'
    $key = Join-Path $certDir 'dev-lan.key'
    $stamp = Join-Path $certDir 'dev-lan.ips'
    $want = ($lanIps -join ',')
    $have = if (Test-Path $stamp) { (Get-Content $stamp -Raw).Trim() } else { '' }
    if (-not (Test-Path $crt) -or -not (Test-Path $key) -or $have -ne $want) {
        $openssl = (Get-Command openssl -ErrorAction SilentlyContinue).Source
        if (-not $openssl) {
            $openssl = @("$env:ProgramFiles\Git\usr\bin\openssl.exe", "$env:ProgramFiles\Git\mingw64\bin\openssl.exe") |
                Where-Object { Test-Path $_ } | Select-Object -First 1
        }
        if ($openssl) {
            New-Item -ItemType Directory -Force -Path $certDir | Out-Null
            $san = (@($lanIps | ForEach-Object { "IP:$_" }) + @('IP:127.0.0.1', 'DNS:localhost')) -join ','
            # openssl prints key-generation progress on stderr, which Windows
            # PowerShell 5.1 turns into a terminating error under 'Stop'.
            $ErrorActionPreference = 'Continue'
            & $openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 825 -quiet -keyout $key -out $crt `
                -subj '/CN=StemDeck dev/O=StemDeck' -addext "subjectAltName=$san" 2>&1 | Out-Null
            $ok = $LASTEXITCODE -eq 0
            $ErrorActionPreference = 'Stop'
            if ($ok) { Set-Content -Path $stamp -Value $want -NoNewline }
            else { Write-Host "AVISO: openssl no pudo crear el certificado; no se puede compartir." -ForegroundColor Yellow }
        } else {
            Write-Host "AVISO: no encuentro openssl (viene con Git for Windows); no se puede compartir." -ForegroundColor Yellow
        }
    }
    if ((Test-Path $crt) -and (Test-Path $key)) {
        $env:STEMDECK_HTTPS_PORT = "$httpsPort"
        $env:STEMDECK_SSL_CERT = $crt
        $env:STEMDECK_SSL_KEY = $key
        $addr = "https://$(TabletIp):$httpsPort"
        ShowShared $addr
        $qr = "$url/api/qr?url=$([uri]::EscapeDataString("$addr/mobile/"))"
    }
} else {
    Write-Host "Solo para este PC. Para usarlo desde el celular o la tablet, abre 'Compartir StemDeck en la red'." -ForegroundColor DarkCyan
}

$log = Join-Path $root '.run\dev-start.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
$helper = {
    param($api, $url, $cookies, $log, $qr)
    function Note($text) { Add-Content -Path $log -Value ("{0:HH:mm:ss} {1}" -f (Get-Date), $text) }
    Note "esperando al servidor en $api"
    $up = $false
    for ($i = 0; $i -lt 180; $i++) {
        try { Invoke-RestMethod "$api/api/health" -TimeoutSec 3 | Out-Null; $up = $true; break } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $up) { Note "el servidor no respondio"; return }
    try {
        $current = (Invoke-RestMethod "$api/api/settings" -TimeoutSec 10).cookies_file
        if (Test-Path $cookies) {
            $body = @{ cookies_file = $cookies } | ConvertTo-Json
            $r = Invoke-RestMethod -Method Post "$api/api/settings" -ContentType 'application/json' -Body $body -TimeoutSec 10
            Note ("cookies de YouTube configuradas: " + $r.cookies_file)
        } elseif ($current -and ($current -eq $cookies)) {
            $body = @{ cookies_file = '' } | ConvertTo-Json
            Invoke-RestMethod -Method Post "$api/api/settings" -ContentType 'application/json' -Body $body -TimeoutSec 10 | Out-Null
            Note "youtube-cookies.txt ya no existe: cookies desactivadas"
        } else {
            Note "sin youtube-cookies.txt"
        }
    } catch { Note ("error configurando cookies: " + $_.Exception.Message) }
    Start-Process $url
    Note "navegador abierto en $url"
    if ($qr) { Start-Process $qr; Note "codigo QR abierto: $qr" }
}
Start-Job -ScriptBlock $helper -ArgumentList $api, $url, $cookies, $log, $qr | Out-Null

Write-Host "Iniciando StemDeck en $url  (Ctrl+C para detenerlo)" -ForegroundColor Cyan
& $uvicorn app.main:app --host 127.0.0.1 --port $port --loop asyncio:ProactorEventLoop --timeout-graceful-shutdown 5
