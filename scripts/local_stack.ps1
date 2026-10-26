#Requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet('Init', 'PullImages', 'Up', 'Stop', 'Status', 'Logs', 'PullEmbedding')]
    [string]$Action = 'Status',
    [ValidateRange(1024, 65535)][int]$HttpPort = 18080,
    [ValidateRange(1024, 65535)][int]$OllamaPort = 11435,
    [ValidateSet('docker.io', 'docker.m.daocloud.io')][string]$ImagePrefix = 'docker.io',
    [string]$PullProxy = ''
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSEdition -ne 'Core') { throw 'Use pwsh 7+, not Windows PowerShell' }
$Root = Split-Path $PSScriptRoot -Parent
$Vendor = Join-Path $Root 'work/vendor/dify'
$DockerDir = Join-Path $Vendor 'docker'
$EnvFile = Join-Path $DockerDir '.env'
$Override = Join-Path $Root 'deploy/compose.local.yaml'
$DifyTag = '1.18.0'
$DifyRevision = '50abea97062110044f15d0e03ccecadd9ccc87ca'

function New-LocalSecret {
    [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
}

if ($Action -eq 'Init') {
    if (-not (Test-Path -LiteralPath (Join-Path $Vendor '.git'))) {
        New-Item -ItemType Directory -Force -Path (Split-Path $Vendor -Parent) | Out-Null
        & git clone --depth 1 --filter=blob:none --sparse --branch $DifyTag https://github.com/langgenius/dify.git $Vendor
        if ($LASTEXITCODE -ne 0) { throw 'Unable to download pinned upstream Dify source' }
        & git -C $Vendor sparse-checkout set docker
        if ($LASTEXITCODE -ne 0) { throw 'Unable to prepare upstream Docker files' }
    }
    $Revision = (& git -C $Vendor rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $Revision -ne $DifyRevision) {
        throw 'Existing vendor checkout does not match the pinned version; it was not reset'
    }
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        if ($HttpPort -eq $OllamaPort) { throw 'Dify and Ollama need different host ports' }
        $Origin = "http://127.0.0.1:$HttpPort"
        $SandboxKey = New-LocalSecret
        $RedisPassword = New-LocalSecret
        $Values = [ordered]@{
            AKB_HTTP_PORT = "$HttpPort"
            AKB_OLLAMA_PORT = "$OllamaPort"
            AKB_IMAGE_PREFIX = $ImagePrefix
            CONSOLE_API_URL = $Origin
            CONSOLE_WEB_URL = $Origin
            SERVICE_API_URL = $Origin
            APP_API_URL = $Origin
            APP_WEB_URL = $Origin
            FILES_URL = $Origin
            INTERNAL_FILES_URL = 'http://api:5001'
            TRIGGER_URL = $Origin
            NEXT_PUBLIC_SOCKET_URL = "ws://127.0.0.1:$HttpPort"
            SECRET_KEY = (New-LocalSecret)
            INIT_PASSWORD = (New-LocalSecret).Substring(0, 24)
            DB_PASSWORD = (New-LocalSecret)
            REDIS_PASSWORD = $RedisPassword
            CELERY_BROKER_URL = "redis://:${RedisPassword}@redis:6379/1"
            VECTOR_STORE = 'qdrant'
            QDRANT_URL = 'http://qdrant:6333'
            QDRANT_API_KEY = (New-LocalSecret)
            COMPOSE_PROFILES = 'qdrant,postgresql'
            ENABLE_COLLABORATION_MODE = 'false'
            NGINX_SOCKET_IO_UPSTREAM = 'api:5001'
            NEXT_TELEMETRY_DISABLED = '1'
            CELERY_WORKER_AMOUNT = '2'
            PLUGIN_DAEMON_KEY = (New-LocalSecret)
            PLUGIN_DIFY_INNER_API_KEY = (New-LocalSecret)
            DIFY_AGENT_API_TOKEN = (New-LocalSecret)
            DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN = (New-LocalSecret)
            DIFY_AGENT_SERVER_SECRET_KEY = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).TrimEnd('=').Replace('+','-').Replace('/','_')
            CODE_EXECUTION_API_KEY = $SandboxKey
            SANDBOX_API_KEY = $SandboxKey
            SSRF_PROXY_ALLOW_PRIVATE_DOMAINS = 'ollama'
            PIP_MIRROR_URL = 'https://pypi.tuna.tsinghua.edu.cn/simple'
            PLUGIN_PYTHON_ENV_INIT_TIMEOUT = '300'
            CONSOLE_CORS_ALLOW_ORIGINS = $Origin
            WEB_API_CORS_ALLOW_ORIGINS = $Origin
        }
        $Lines = [Collections.Generic.List[string]]::new()
        foreach ($Line in [IO.File]::ReadAllLines((Join-Path $DockerDir '.env.example'))) {
            if ($Line -match '^([A-Za-z_][A-Za-z_0-9]*)=' -and $Values.Contains($Matches[1])) {
                $Key = $Matches[1]
                $Lines.Add("$Key=$($Values[$Key])")
                $Values.Remove($Key)
            } else { $Lines.Add($Line) }
        }
        foreach ($Key in $Values.Keys) { $Lines.Add("$Key=$($Values[$Key])") }
        [IO.File]::WriteAllLines($EnvFile, $Lines, [Text.UTF8Encoding]::new($false))
        Write-Output 'Created private runtime settings with fresh local secrets. No model API key was set.'
    } else {
        Write-Output 'Keeping existing runtime settings and secrets. Port parameters apply only on first Init.'
        if ($PSBoundParameters.ContainsKey('ImagePrefix')) {
            $Content = [IO.File]::ReadAllText($EnvFile)
            if ($Content -match '(?m)^AKB_IMAGE_PREFIX=') {
                $Content = [regex]::Replace($Content, '(?m)^AKB_IMAGE_PREFIX=[^\r\n]*', "AKB_IMAGE_PREFIX=$ImagePrefix")
            } else { $Content += "`nAKB_IMAGE_PREFIX=$ImagePrefix`n" }
            [IO.File]::WriteAllText($EnvFile, $Content, [Text.UTF8Encoding]::new($false))
            Write-Output "This project's public image download source: $ImagePrefix"
        }
    }
}

if (-not (Test-Path -LiteralPath $EnvFile)) { throw 'Run -Action Init first' }
$ComposeArgs = @(
    'compose', '--parallel', '2', '--project-name', 'animation-kb', '--project-directory', $DockerDir,
    '--env-file', $EnvFile, '-f', (Join-Path $DockerDir 'docker-compose.yaml'), '-f', $Override
)

function Import-StackImages {
    # This is an optional per-command path for engines whose global proxy is unavailable.
    # Only public container images pass through the proxy, never project source data.
    $Crane = Join-Path $Root 'work/bin/crane.exe'
    $Archive = Join-Path $Root 'work/bin/crane.tar.gz'
    New-Item -ItemType Directory -Force -Path (Split-Path $Crane -Parent), (Join-Path $Root 'work/images'), (Join-Path $Root 'work/image-cache'), (Join-Path $Root 'work/registry-auth') | Out-Null
    if (-not (Test-Path -LiteralPath $Crane)) {
        $DownloadArgs = @('--location', '--fail', '--http1.1', '--connect-timeout', '15', '--max-time', '120', '--silent', '--show-error')
        if ($PullProxy) { $DownloadArgs += @('--proxy', $PullProxy) }
        & curl.exe @DownloadArgs --output $Archive 'https://github.com/google/go-containerregistry/releases/download/v0.22.1/go-containerregistry_Windows_x86_64.tar.gz'
        if ($LASTEXITCODE -ne 0) { throw 'Official crane download failed' }
        & tar -xzf $Archive -C (Split-Path $Crane -Parent) crane.exe
        if ($LASTEXITCODE -ne 0) { throw 'Cannot extract official crane utility' }
    }
    if ((& $Crane version).Trim() -ne '0.22.1') { throw 'Unexpected crane version; existing utility was not overwritten' }
    $Images = @(& docker @ComposeArgs config --images | Sort-Object -Unique)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve this project image list' }
    $Saved = @{}
    foreach ($Name in 'HTTP_PROXY','HTTPS_PROXY','DOCKER_CONFIG','GODEBUG') { $Saved[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process') }
    try {
        if ($PullProxy) {
            $env:HTTP_PROXY = $PullProxy
            $env:HTTPS_PROXY = $PullProxy
        }
        $env:GODEBUG = 'http2client=0'
        foreach ($Image in $Images) {
            $env:DOCKER_CONFIG = $Saved['DOCKER_CONFIG']
            # `image ls` does not normalize the Docker Hub prefix like image inspect does.
            $LocalRef = $Image -replace '^docker\.io/(library/)?', ''
            $Local = & docker image ls --quiet $LocalRef
            if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect local Docker images' }
            if ($Local) { Write-Output "Keeping cached image $Image"; continue }
            $TarPath = Join-Path $Root ("work/images/" + ($Image -replace '[/:]', '_') + '.tar')
            Write-Output "Downloading public image $Image through this invocation only"
            # Avoid loading unrelated Docker login credentials into the download helper.
            $env:DOCKER_CONFIG = Join-Path $Root 'work/registry-auth'
            & $Crane pull --cache_path (Join-Path $Root 'work/image-cache') --platform linux/amd64 $Image $TarPath
            if ($LASTEXITCODE -ne 0) { throw "Image download failed: $Image" }
            $env:DOCKER_CONFIG = $Saved['DOCKER_CONFIG']
            & docker load -i $TarPath
            if ($LASTEXITCODE -ne 0) { throw "Image import failed: $Image" }
        }
    } finally {
        foreach ($Name in $Saved.Keys) { [Environment]::SetEnvironmentVariable($Name, $Saved[$Name], 'Process') }
    }
}

switch ($Action) {
    'Init' { & docker @ComposeArgs config --quiet }
    'PullImages' { Import-StackImages }
    'Up' { & docker @ComposeArgs up -d --pull never }
    'Stop' { & docker @ComposeArgs stop }
    'Status' { & docker @ComposeArgs ps }
    'Logs' { & docker @ComposeArgs logs --tail 60 api worker plugin_daemon ollama }
    'PullEmbedding' { & docker @ComposeArgs exec -T ollama ollama pull bge-m3 }
}
if ($LASTEXITCODE -ne 0) { throw "Local stack action $Action failed (exit $LASTEXITCODE)" }
