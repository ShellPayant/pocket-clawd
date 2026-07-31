# Pocket Clawd pusher for Windows, in PowerShell -- no Python needed.
#
#   powershell -ExecutionPolicy Bypass -File clawd-pusher.ps1
#
# It finds the console by listening for the UDP beacon the console sends, so
# there is normally no address to type. Override with -Device if you want to.
#
#   -Device 192.168.1.42     talk to this address instead of discovering
#   -Secret "..."            must match "secret" in the console's config.json
#   -Hotspot                 keep the Windows Mobile Hotspot switched on
#   -DryRun                  print the data once and exit
#
# Where the numbers come from: Claude Code stores an OAuth token on this PC
# when you log in. This reads it and asks Anthropic for your own usage. The
# token is never sent anywhere except to Anthropic, and the console only ever
# receives percentages.
param(
    [string[]]$Device = @(),
    [string]$Secret = "",
    [switch]$Hotspot,
    [switch]$NoDiscovery,
    [switch]$DryRun,
    [int]$Interval = 120
)

$ErrorActionPreference = "Continue"
$PushEvery = 60
$RateBackoff = 300
$DiscoveryPort = 8787
$CredFile = "$env:USERPROFILE\.claude\.credentials.json"
$ProjectsDir = "$env:USERPROFILE\.claude\projects"
$SessionsDir = "$env:USERPROFILE\.claude\sessions"

function Say([string]$m) { Write-Host "$(Get-Date -Format HH:mm:ss)  $m" }

# --- single instance --------------------------------------------------------
$script:mutex = New-Object System.Threading.Mutex($false, 'Global\PocketClawdPusher')
try {
    $owned = $script:mutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    # the previous copy was killed rather than closed; the mutex is ours now
    $owned = $true
}
if (-not $owned) {
    Say "Another pusher is already running - this window can be closed."
    Start-Sleep 4
    exit 0
}

# --- optional: keep the Windows hotspot up ----------------------------------
# Only needed if the console joins a hotspot hosted by this PC, which is the
# workaround for home networks that are 5GHz or WPA3 only.
if ($Hotspot) {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $script:asTaskOp = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
            $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        })[0]
    [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime] | Out-Null
    [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime] | Out-Null
}

function Ensure-Hotspot {
    if (-not $Hotspot) { return }
    try {
        $prof = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
        $tm = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($prof)
        if ($tm.TetheringOperationalState -eq 'Off') {
            Say "hotspot was off - switching it back on"
            $t = $script:asTaskOp.MakeGenericMethod(
                [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult]
            ).Invoke($null, @($tm.StartTetheringAsync()))
            $t.Wait(20000) | Out-Null
        }
    } catch {
        Say "hotspot check failed: $($_.Exception.Message)"
    }
}

# --- discovery: listen for the console announcing itself --------------------
$script:udp = $null
if (-not $NoDiscovery) {
    try {
        $script:udp = New-Object System.Net.Sockets.UdpClient
        $script:udp.Client.SetSocketOption([System.Net.Sockets.SocketOptionLevel]::Socket,
            [System.Net.Sockets.SocketOptionName]::ReuseAddress, $true)
        $script:udp.Client.Bind(
            (New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, $DiscoveryPort)))
    } catch {
        Say "discovery unavailable ($($_.Exception.Message)); use -Device instead"
        $script:udp = $null
    }
}
$script:found = @{}

function Poll-Discovery {
    if ($null -eq $script:udp) { return }
    while ($script:udp.Available -gt 0) {
        $remote = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
        try { $raw = $script:udp.Receive([ref]$remote) } catch { return }
        try { $msg = [Text.Encoding]::UTF8.GetString($raw) | ConvertFrom-Json } catch { continue }
        if ($msg.app -ne "pocket-clawd") { continue }
        if ($msg.mode -eq "pull") { continue }   # pull mode needs the Python pusher
        $port = if ($msg.port) { [int]$msg.port } else { 8788 }
        $url = "http://$($remote.Address):$port/"
        if (-not $script:found.ContainsKey($url)) { Say "found a console at $url" }
        $script:found[$url] = Get-Date
    }
}

function Get-Targets {
    $urls = @()
    foreach ($d in $Device) {
        if ($d -like "http*") { $urls += $d } else { $urls += "http://${d}:8788/" }
    }
    $cutoff = (Get-Date).AddSeconds(-90)
    foreach ($k in $script:found.Keys) { if ($script:found[$k] -gt $cutoff) { $urls += $k } }
    return $urls
}

# --- the data ---------------------------------------------------------------
function Format-Reset([string]$iso) {
    try {
        $d = [datetimeoffset]::Parse($iso).ToLocalTime()
        if ($d.Date -eq (Get-Date).Date) { return $d.ToString("HH:mm") }
        return $d.ToString("ddd HH:mm").ToUpper()
    } catch { return "?" }
}

function Get-ProjectName([string]$dir) {
    $parts = $dir -split '-+' | Where-Object { $_ }
    if ($parts.Count -eq 0) { return $dir.ToUpper() }
    $n = $parts[-1].ToUpper()
    if ($n.Length -gt 10) { return $n.Substring(0, 10) }
    return $n
}

# Words that name the tool rather than the project. Lots of people keep their
# work under a "Claude" folder, and labelling six projects CLAUDE helps nobody.
$GenericParts = @('CLAUDE', 'CODE', 'DEV', 'SRC', 'PROJECTS', 'REPOS', 'WORK')

function Get-ProjectLabel([string]$cwd) {
    # Only ever the last meaningful part of the path -- the full path contains
    # the user's home directory and is never sent anywhere.
    $base = ($cwd -replace '\\', '/').TrimEnd('/') -split '/' | Select-Object -Last 1
    $parts = $base -split '\s*-\s+|\s+|_' | Where-Object { $_ }
    if ($parts.Count -eq 0) { return "PROJECT" }
    $label = $parts[-1]
    if (($GenericParts -contains $label.ToUpper()) -and $parts.Count -gt 1) {
        $label = $parts[-2]
    }
    $label = $label.ToUpper()
    if ($label.Length -gt 10) { $label = $label.Substring(0, 10) }
    return $label
}

function Get-LiveSessions {
    # ~/.claude/sessions/<pid>.json is one file per running CLI, with the real
    # working directory and a busy/idle status. Returns $null when it isn't
    # there so the caller can fall back -- it is an internal file and may change.
    if (-not (Test-Path $SessionsDir)) { return $null }
    try {
        $files = Get-ChildItem $SessionsDir -Filter *.json -ErrorAction Stop
    } catch { return $null }
    if (-not $files) { return $null }
    # one process list, rather than probing each pid separately
    $running = @{}
    Get-Process -ErrorAction SilentlyContinue | ForEach-Object { $running[$_.Id] = $true }

    $order = @()
    $groups = @{}
    foreach ($f in $files) {
        try { $d = Get-Content $f.FullName -Raw | ConvertFrom-Json } catch { continue }
        if (-not $d.pid -or -not $d.cwd) { continue }
        if ($d.kind -and $d.kind -ne 'interactive') { continue }
        if (-not $running.ContainsKey([int]$d.pid)) { continue }   # stale file
        $label = Get-ProjectLabel $d.cwd
        if (-not $groups.ContainsKey($label)) {
            $groups[$label] = @{ n = $label; c = 0; b = 0 }
            $order += $label
        }
        $groups[$label].c++
        if ("$($d.status)".ToLower() -eq 'busy') { $groups[$label].b = 1 }
    }
    if ($order.Count -eq 0) { return $null }
    return @($order | Select-Object -First 5 | ForEach-Object { $groups[$_] })
}

function Get-ScannedSessions {
    # Fallback: projects whose transcript was written to recently. Coarser --
    # it cannot tell two terminals in one project apart.
    try {
        $active = @()
        Get-ChildItem $ProjectsDir -Directory -ErrorAction Stop | ForEach-Object {
            $recent = Get-ChildItem $_.FullName -Filter *.jsonl -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-5) } |
                Select-Object -First 1
            if ($recent) { $active += (Get-ProjectName $_.Name) }
        }
        return @($active | Select-Object -Unique -First 5 |
            ForEach-Object { @{ n = $_; c = 1; b = 0 } })
    } catch { return @() }
}

function Get-SessionInfo {
    $info = Get-LiveSessions
    if ($null -eq $info) { $info = Get-ScannedSessions }
    return @($info)
}

function Get-Payload {
    $tok = (Get-Content $CredFile -Raw | ConvertFrom-Json).claudeAiOauth.accessToken
    $u = Invoke-RestMethod -Uri 'https://api.anthropic.com/api/oauth/usage' -TimeoutSec 15 -Headers @{
        'Authorization'  = "Bearer $tok"
        'anthropic-beta' = 'oauth-2025-04-20'
        'User-Agent'     = 'pocket-clawd-pusher'
    }
    $scopedPct = 0
    $scopedLabel = "SCOPED"
    foreach ($l in $u.limits) {
        if ($l.kind -eq 'weekly_scoped') {
            $scopedPct = [int]$l.percent
            $name = $null
            if ($l.scope -and $l.scope.model) {
                $name = $l.scope.model.display_name
                if (-not $name) { $name = $l.scope.model.id }
            }
            if ($name) {
                $scopedLabel = ($name -split '-')[0].ToUpper()
                if ($scopedLabel.Length -gt 9) { $scopedLabel = $scopedLabel.Substring(0, 9) }
            }
        }
    }
    $info = Get-SessionInfo
    $note = $null
    try {
        $proj = Get-ChildItem $ProjectsDir -Directory -ErrorAction Stop |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($proj) { $note = "LAST PROJECT: $(Get-ProjectName $proj.Name)" }
    } catch { }
    return @{
        five_hour_pct   = [int]$u.five_hour.utilization
        five_hour_reset = Format-Reset $u.five_hour.resets_at
        seven_day_pct   = [int]$u.seven_day.utilization
        seven_day_reset = Format-Reset $u.seven_day.resets_at
        scoped_pct      = $scopedPct
        scoped_label    = $scopedLabel
        updated         = (Get-Date).ToString("HH:mm")
        epoch           = [DateTimeOffset]::Now.ToUnixTimeSeconds()
        note            = $note
        # legacy: names only, so an older console still works
        sessions        = (($info | ForEach-Object { $_.n }) -join ",")
        # n=name, c=how many terminals in it, b=any of them busy right now
        session_info    = $info
        rl              = 0
    }
}

if (-not (Test-Path $CredFile)) {
    Say "No Claude Code credentials at $CredFile - log in with Claude Code first."
    exit 1
}

if ($DryRun) {
    Get-Payload | ConvertTo-Json
    exit 0
}

Say "Watching your Claude usage. Ctrl+C to stop."
if ($Device.Count) { Say "configured console(s): $($Device -join ', ')" }
elseif ($script:udp) { Say "looking for a console on the network..." }

$script:cached = $null
$script:rl = 0
$nextFetch = Get-Date
$nextPush = Get-Date
$known = @{}

while ($true) {
    Ensure-Hotspot
    Poll-Discovery

    if ((Get-Date) -ge $nextFetch) {
        try {
            $script:cached = Get-Payload
            $script:rl = 0
            $nextFetch = (Get-Date).AddSeconds([Math]::Max(30, $Interval))
            Say ("usage: 5h {0}%  7d {1}%  {2} {3}%" -f $script:cached.five_hour_pct,
                $script:cached.seven_day_pct, $script:cached.scoped_label,
                $script:cached.scoped_pct)
        } catch {
            $msg = $_.Exception.Message
            if ($msg -match '429') {
                $script:rl = 1
                $nextFetch = (Get-Date).AddSeconds($RateBackoff)
                Say "rate limited by Anthropic; retrying in $RateBackoff s"
            } elseif ($msg -match '401' -or $msg -match '403') {
                $nextFetch = (Get-Date).AddSeconds($RateBackoff)
                Say "credentials rejected - log in with Claude Code again"
            } else {
                $nextFetch = (Get-Date).AddSeconds(60)
                Say "usage fetch failed: $msg"
            }
        }
    }

    $targets = Get-Targets
    $appeared = @($targets | Where-Object { -not $known.ContainsKey($_) })
    # push on the timer, but also the moment a console turns up
    if ($script:cached -and (((Get-Date) -ge $nextPush) -or $appeared.Count)) {
        $nextPush = (Get-Date).AddSeconds($PushEvery)
        $send = @{} + $script:cached
        $send.rl = [int]$script:rl
        $send.updated = (Get-Date).ToString("HH:mm")
        $send.epoch = [DateTimeOffset]::Now.ToUnixTimeSeconds()
        $fresh = Get-SessionInfo
        $send.sessions = (($fresh | ForEach-Object { $_.n }) -join ",")
        $send.session_info = $fresh
        $body = $send | ConvertTo-Json -Compress
        # Content-Type goes via -ContentType only: PowerShell 5.1 throws
        # "The 'Content-Type' header must be modified using the appropriate
        # property or method" if it is also present in -Headers.
        $headers = @{}
        if ($Secret) { $headers['X-Clawd-Secret'] = $Secret }
        $sent = 0
        foreach ($url in $targets) {
            try {
                Invoke-RestMethod -Uri $url -Method Post -Body $body -Headers $headers `
                    -ContentType 'application/json' -TimeoutSec 5 | Out-Null
                $known[$url] = $true
                $sent++
            } catch {
                Say "could not reach $url"
                $known.Remove($url)
            }
        }
        if ($targets.Count -and -not $sent) { Say "no console reachable" }
    }
    Start-Sleep -Seconds 2
}
