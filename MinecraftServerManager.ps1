#Requires -Version 5.1
<#
.SYNOPSIS
    Minecraft server + world manager (Podman/Quadlet) over SSH.
.DESCRIPTION
    Single-screen dashboard. Hotkeys for all operations.
    Container operations run as the podman user (systemctl --user, podman exec).
    World file operations (editing server.properties, deleting world folders)
    run as an admin user with sudo. Sudo password is requested once at startup.
    By default the SSH key id_rsa_home is expected next to this script.
.PARAMETER SshHost
    Server hostname or IP. Default: 192.168.100.100
.PARAMETER PodmanUser
    User that owns the user-scope systemd units. Default: podman-svc
.PARAMETER AdminUser
    User with sudo rights for editing world files. Default: jan
.PARAMETER SshKey
    Path to the SSH private key used for both connections.
    Default: <script folder>\id_rsa_home
.PARAMETER AdminKey
    Optional separate key for the admin user. Defaults to SshKey.
#>
[CmdletBinding()]
param(
    [string]$SshHost    = "192.168.100.100",
    [string]$PodmanUser = "podman-svc",
    [string]$AdminUser  = "jan",
    [string]$SshKey     = "",
    [string]$AdminKey   = ""
)

if ([string]::IsNullOrWhiteSpace($SshKey)) {
    if ($PSScriptRoot) {
        $SshKey = Join-Path $PSScriptRoot "id_rsa_home"
    } else {
        $SshKey = Join-Path (Get-Location) "id_rsa_home"
    }
}
if ([string]::IsNullOrWhiteSpace($AdminKey)) { $AdminKey = $SshKey }

$PodmanTarget = "$PodmanUser@$SshHost"
$AdminTarget  = "$AdminUser@$SshHost"

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding           = [System.Text.Encoding]::UTF8
} catch { }

# ---------- Server config ----------
$Server = [PSCustomObject]@{
    Name    = "minecraft-1"
    Service = "minecraft-forge_1.service"
    Port    = 25565
    Label   = "Forge 1.20.1"
}
$DataPath    = "/mnt/library/containers/minecraft/data"
$ServerProps = "$DataPath/server.properties"
$WorldPrefix = "world_"

# Runtime state
$script:SudoPassword  = ""
$script:SudoUseNoPass = $false

# =================== REMOTE HELPERS ===================

function Invoke-Podman {
    param([Parameter(Mandatory)][string]$Command)
    ssh -i $SshKey -o BatchMode=yes $PodmanTarget $Command 2>&1
}

function Invoke-SshWithStdin {
    param(
        [Parameter(Mandatory)][string]$KeyPath,
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string]$RemoteCommand,
        [string]$StdinText = ""
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = "ssh"
    $psi.Arguments              = '-i "' + $KeyPath + '" -o BatchMode=yes -T ' + $Target + ' "' + $RemoteCommand + '"'
    $psi.UseShellExecute        = $false
    $psi.RedirectStandardInput  = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.CreateNoWindow         = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding  = [System.Text.Encoding]::UTF8

    $proc = [System.Diagnostics.Process]::Start($psi)
    if ($StdinText) { $proc.StandardInput.Write($StdinText + "`n") }
    $proc.StandardInput.Close()

    $out = $proc.StandardOutput.ReadToEnd()
    $err = $proc.StandardError.ReadToEnd()
    $proc.WaitForExit()

    $combined = $out
    if ($err) {
        if ($combined) { $combined += "`n" }
        $combined += $err
    }
    return @{ Output = $combined; ExitCode = $proc.ExitCode }
}

function Invoke-AdminSudo {
    param([Parameter(Mandatory)][string]$Command)

    if ($script:SudoUseNoPass) {
        $r = Invoke-SshWithStdin -KeyPath $AdminKey -Target $AdminTarget -RemoteCommand "sudo -n $Command"
        return $r.Output
    }
    $r = Invoke-SshWithStdin -KeyPath $AdminKey -Target $AdminTarget `
            -RemoteCommand "sudo -S -p '' $Command" `
            -StdinText $script:SudoPassword
    return $r.Output
}

function Test-SshConnection {
    $null = ssh -i $SshKey -o BatchMode=yes -o ConnectTimeout=5 $PodmanTarget "echo ok" 2>&1
    return ($LASTEXITCODE -eq 0)
}

function Test-SshConnectionAdmin {
    $null = ssh -i $AdminKey -o BatchMode=yes -o ConnectTimeout=5 $AdminTarget "echo ok" 2>&1
    return ($LASTEXITCODE -eq 0)
}

function Test-SudoPassword {
    param([Parameter(Mandatory)][string]$Password)
    $r = Invoke-SshWithStdin -KeyPath $AdminKey -Target $AdminTarget `
            -RemoteCommand "sudo -S -p '' true" `
            -StdinText $Password
    return ($r.ExitCode -eq 0)
}

# =================== STATE ===================

function Get-DashboardData {
    # One SSH roundtrip returns everything needed to render the dashboard.
    $cmd = "systemctl --user is-active $($Server.Service) 2>/dev/null; " +
           "echo '===WORLDS==='; " +
           "ls -1 $DataPath 2>/dev/null | grep -E '^world(_[a-zA-Z0-9_-]+)?$' | grep -v '_nether$' | grep -v '_the_end$' | sort; " +
           "echo '===LEVEL==='; " +
           "grep '^level-name=' $ServerProps 2>/dev/null | cut -d= -f2"

    $out = ssh -i $SshKey -o BatchMode=yes $PodmanTarget $cmd 2>$null
    $lines = @($out) | ForEach-Object { $_.TrimEnd("`r") }

    $state = "inactive"
    $worlds = @()
    $level = ""

    $mode = "state"
    foreach ($line in $lines) {
        if ($line -eq "===WORLDS===") { $mode = "worlds"; continue }
        if ($line -eq "===LEVEL===")  { $mode = "level";  continue }
        switch ($mode) {
            "state"  { if ($line) { $state = $line } }
            "worlds" { if ($line) { $worlds += $line } }
            "level"  { if ($line) { $level = $line } }
        }
    }

    return @{ State = $state; Worlds = $worlds; Current = $level }
}

function Get-StateLabel {
    param([string]$State)
    switch ($State) {
        "active"       { return @{ Text = "RUNNING";  Color = "Green"    } }
        "activating"   { return @{ Text = "STARTING"; Color = "Yellow"   } }
        "deactivating" { return @{ Text = "STOPPING"; Color = "Yellow"   } }
        "failed"       { return @{ Text = "FAILED";   Color = "Red"      } }
        default        { return @{ Text = "STOPPED";  Color = "DarkGray" } }
    }
}

function Set-CurrentWorld {
    param([Parameter(Mandatory)][string]$WorldName)

    $cmd = "sed -i 's|^level-name=.*|level-name=$WorldName|' $ServerProps"
    Invoke-AdminSudo $cmd | Out-Null

    $check = (Get-DashboardData).Current
    if ($check -ne $WorldName) {
        Write-Host ""
        Write-Host "ERROR: failed to update level-name." -ForegroundColor Red
        Write-Host "  Expected: $WorldName" -ForegroundColor Yellow
        Write-Host "  Got     : $check" -ForegroundColor Yellow
        Read-Host "Press Enter" | Out-Null
        return $false
    }
    return $true
}

function Remove-WorldFiles {
    param([Parameter(Mandatory)][string]$WorldName)
    $cmd = "rm -rf '$DataPath/$WorldName' '$DataPath/${WorldName}_nether' '$DataPath/${WorldName}_the_end'"
    Invoke-AdminSudo $cmd | Out-Null
}

# =================== DASHBOARD RENDERING ===================

function Show-Dashboard {
    param([string]$Flash = "")

    $d     = Get-DashboardData
    $label = Get-StateLabel -State $d.State

    Clear-Host
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ("  Minecraft Server Manager  --  {0}" -f $SshHost) -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan

    Write-Host ("  Server : {0}  port {1}  [" -f $Server.Label, $Server.Port) -NoNewline
    Write-Host $label.Text -NoNewline -ForegroundColor $label.Color
    Write-Host "]"
    Write-Host ("  World  : {0}" -f $d.Current) -ForegroundColor DarkCyan

    if ($Flash) {
        Write-Host ""
        Write-Host ("  * " + $Flash) -ForegroundColor Yellow
    }

    Write-Host "------------------------------------------------------------" -ForegroundColor DarkGray
    Write-Host "  " -NoNewline
    Write-Host "[S]" -NoNewline -ForegroundColor Yellow; Write-Host "tart  " -NoNewline
    Write-Host "[X]" -NoNewline -ForegroundColor Yellow; Write-Host " stop  " -NoNewline
    Write-Host "[R]" -NoNewline -ForegroundColor Yellow; Write-Host "estart  " -NoNewline
    Write-Host "[L]" -NoNewline -ForegroundColor Yellow; Write-Host "ogs  " -NoNewline
    Write-Host "[C]" -NoNewline -ForegroundColor Yellow; Write-Host "onsole  " -NoNewline
    Write-Host "[Q]" -NoNewline -ForegroundColor Yellow; Write-Host "uit"

    Write-Host "------------------------------------------------------------" -ForegroundColor DarkGray
    Write-Host "  Worlds:"
    if ($d.Worlds.Count -eq 0) {
        Write-Host "   (none yet)" -ForegroundColor DarkGray
    } else {
        $limit = [Math]::Min($d.Worlds.Count, 9)
        for ($i = 0; $i -lt $limit; $i++) {
            $marker = if ($d.Worlds[$i] -eq $d.Current) { "  <- active" } else { "" }
            $color  = if ($d.Worlds[$i] -eq $d.Current) { "Green" } else { "Gray" }
            Write-Host ("   [{0}] {1}{2}" -f ($i + 1), $d.Worlds[$i], $marker) -ForegroundColor $color
        }
        if ($d.Worlds.Count -gt 9) {
            Write-Host ("   ... and {0} more" -f ($d.Worlds.Count - 9)) -ForegroundColor DarkGray
        }
    }

    Write-Host "  " -NoNewline
    Write-Host "[N]" -NoNewline -ForegroundColor Yellow; Write-Host "ew  " -NoNewline
    Write-Host "[D]" -NoNewline -ForegroundColor Yellow; Write-Host "elete  " -NoNewline
    Write-Host "[T]" -NoNewline -ForegroundColor Yellow; Write-Host " reset current"
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  Press a key (any other to refresh): " -NoNewline
}

# =================== ACTIONS ===================

function Action-Start {
    Write-Host ""
    Write-Host "Starting ..." -ForegroundColor Yellow
    Invoke-Podman "systemctl --user start $($Server.Service)" | Out-Null
    Start-Sleep -Seconds 3
    return "Server start requested."
}

function Action-Stop {
    Write-Host ""
    Write-Host "Stop server? [y/N]: " -NoNewline
    $k = [Console]::ReadKey($true)
    Write-Host $k.KeyChar
    if ($k.KeyChar -notmatch '^[yY]') { return "Stop cancelled." }
    Write-Host "Stopping ..." -ForegroundColor Yellow
    Invoke-Podman "systemctl --user stop $($Server.Service)" | Out-Null
    Start-Sleep -Seconds 3
    return "Server stop requested."
}

function Action-Restart {
    Write-Host ""
    Write-Host "Restarting ..." -ForegroundColor Yellow
    Invoke-Podman "systemctl --user restart $($Server.Service)" | Out-Null
    Start-Sleep -Seconds 3
    return "Server restart requested."
}

function Action-Logs {
    ssh -i $SshKey -t $PodmanTarget "journalctl --user -u $($Server.Service) -n 100 --no-pager | less -R"
    return "Logs closed."
}

function Action-Console {
    ssh -i $SshKey -tt $PodmanTarget "podman exec -it $($Server.Name) rcon-cli"
    return "Console closed."
}

function Action-SwitchWorld {
    param([string]$WorldName)
    $d = Get-DashboardData
    if ($WorldName -eq $d.Current) {
        return "Already active."
    }
    Write-Host ""
    Write-Host "Switching to '$WorldName' ..." -ForegroundColor Yellow
    if (-not (Set-CurrentWorld -WorldName $WorldName)) { return "" }
    if ($d.State -eq "active") {
        Write-Host "Restart to apply? [y/N]: " -NoNewline
        $k = [Console]::ReadKey($true)
        Write-Host $k.KeyChar
        if ($k.KeyChar -match '^[yY]') {
            Invoke-Podman "systemctl --user restart $($Server.Service)" | Out-Null
            Start-Sleep -Seconds 3
            return "Switched to '$WorldName' and restarted."
        }
    }
    return "level-name set to '$WorldName'. Will apply on next start."
}

function Action-NewWorld {
    Write-Host ""
    Write-Host ("New world will be '${WorldPrefix}<suffix>'. Allowed: A-Z a-z 0-9 _ -") -ForegroundColor DarkGray
    $suffix = Read-Host "Suffix"
    if ([string]::IsNullOrWhiteSpace($suffix)) { return "Cancelled." }
    if ($suffix -notmatch '^[a-zA-Z0-9_-]+$') { return "Invalid characters." }

    $name = "${WorldPrefix}${suffix}"
    $d = Get-DashboardData
    if ($d.Worlds -contains $name) { return "World '$name' already exists." }

    Write-Host ("Create and switch to '$name'? [y/N]: ") -NoNewline
    $k = [Console]::ReadKey($true)
    Write-Host $k.KeyChar
    if ($k.KeyChar -notmatch '^[yY]') { return "Cancelled." }

    if (-not (Set-CurrentWorld -WorldName $name)) { return "" }

    if ($d.State -eq "active") {
        Write-Host "Restart now to generate? [y/N]: " -NoNewline
        $k2 = [Console]::ReadKey($true)
        Write-Host $k2.KeyChar
        if ($k2.KeyChar -match '^[yY]') {
            Invoke-Podman "systemctl --user restart $($Server.Service)" | Out-Null
            Start-Sleep -Seconds 3
            return "Created '$name' and restarted. Generating..."
        }
    }
    return "Created '$name'. Will be generated on next start."
}

function Action-DeleteWorld {
    $d = Get-DashboardData
    $deletable = @($d.Worlds | Where-Object { $_ -ne $d.Current })
    if ($deletable.Count -eq 0) { return "No deletable worlds (only active one)." }

    Write-Host ""
    Write-Host "Deletable worlds:" -ForegroundColor Yellow
    $limit = [Math]::Min($deletable.Count, 9)
    for ($i = 0; $i -lt $limit; $i++) {
        Write-Host ("   [{0}] {1}" -f ($i + 1), $deletable[$i]) -ForegroundColor Gray
    }
    Write-Host "   [0] Cancel"
    Write-Host "Select: " -NoNewline
    $k = [Console]::ReadKey($true)
    Write-Host $k.KeyChar
    if ($k.KeyChar -notmatch '^[1-9]$') { return "Cancelled." }

    $idx = [int]::Parse("$($k.KeyChar)") - 1
    if ($idx -ge $deletable.Count) { return "Out of range." }
    $target = $deletable[$idx]

    Write-Host ""
    Write-Host ("Type '$target' to confirm deletion: ") -NoNewline -ForegroundColor Red
    $confirm = Read-Host
    if ($confirm -ne $target) { return "Cancelled." }

    Write-Host "Deleting '$target' ..." -ForegroundColor Yellow
    Remove-WorldFiles -WorldName $target
    Start-Sleep -Milliseconds 500
    return "Deleted '$target'."
}

function Action-ResetWorld {
    $d = Get-DashboardData
    if (-not $d.Current) { return "Cannot determine current world." }

    Write-Host ""
    Write-Host ("This will PERMANENTLY DELETE the active world '$($d.Current)'.") -ForegroundColor Red
    Write-Host "The server will regenerate a fresh world with the same name." -ForegroundColor Yellow
    Write-Host "Type RESET to confirm: " -NoNewline
    $confirm = Read-Host
    if ($confirm -ne "RESET") { return "Cancelled." }

    Write-Host "Stopping ..." -ForegroundColor Yellow
    Invoke-Podman "systemctl --user stop $($Server.Service)" | Out-Null
    Start-Sleep -Seconds 3

    Write-Host "Deleting '$($d.Current)' ..." -ForegroundColor Yellow
    Remove-WorldFiles -WorldName $d.Current

    Write-Host "Starting ..." -ForegroundColor Yellow
    Invoke-Podman "systemctl --user start $($Server.Service)" | Out-Null
    Start-Sleep -Seconds 3
    return "World '$($d.Current)' is being regenerated."
}

# =================== ENTRY POINT ===================

# ---- 1. SSH key check ----
if (-not (Test-Path -LiteralPath $SshKey)) {
    Write-Host "SSH key not found: $SshKey" -ForegroundColor Red
    Write-Host ""
    Write-Host "Place 'id_rsa_home' next to this script:" -ForegroundColor Yellow
    Write-Host "  $PSScriptRoot\id_rsa_home" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Or pass a custom path:  -SshKey C:\path\to\key" -ForegroundColor Yellow
    Read-Host "Press Enter to exit" | Out-Null
    exit 1
}

# ---- 2. SSH connectivity ----
Write-Host "Testing SSH connection to $PodmanTarget ..." -ForegroundColor Cyan
if (-not (Test-SshConnection)) {
    Write-Host "Cannot connect to $PodmanTarget over SSH." -ForegroundColor Red
    Read-Host "Press Enter to exit" | Out-Null
    exit 1
}

Write-Host "Testing SSH connection to $AdminTarget ..." -ForegroundColor Cyan
if (-not (Test-SshConnectionAdmin)) {
    Write-Host "Cannot connect to $AdminTarget over SSH." -ForegroundColor Red
    Read-Host "Press Enter to exit" | Out-Null
    exit 1
}
Write-Host "OK." -ForegroundColor Green

# ---- 3. Sudo password ----
$probe = ssh -i $AdminKey -o BatchMode=yes $AdminTarget "sudo -n true" 2>&1
if ($LASTEXITCODE -eq 0) {
    $script:SudoUseNoPass = $true
    Write-Host "Passwordless sudo detected for $AdminUser." -ForegroundColor Green
} else {
    Write-Host "Enter sudo password for $AdminUser." -ForegroundColor Yellow
    $sec = Read-Host "Password" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try {
        $script:SudoPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }

    if ([string]::IsNullOrWhiteSpace($script:SudoPassword)) {
        Write-Host "Empty password." -ForegroundColor Yellow
    } elseif (-not (Test-SudoPassword -Password $script:SudoPassword)) {
        Write-Host "sudo rejected the password." -ForegroundColor Red
        Read-Host "Press Enter to exit" | Out-Null
        exit 1
    } else {
        Write-Host "Password accepted." -ForegroundColor Green
    }
}

# ---- 4. Main loop ----
$flash = ""
while ($true) {
    Show-Dashboard -Flash $flash
    $flash = ""

    $k = [Console]::ReadKey($true)
    $ch = $k.KeyChar

    # Ignore control keys (arrows, function keys)
    if ($ch -eq [char]0 -or $ch -eq "`r" -or $ch -eq "`n" -or $ch -eq "`t") {
        continue
    }

    Write-Host $ch

    if ($ch -match '^[Qq]$') {
        Write-Host ""
        Write-Host "Bye." -ForegroundColor Cyan
        exit 0
    }

    if ($ch -match '^[Ss]$') { $flash = Action-Start;        continue }
    if ($ch -match '^[Xx]$') { $flash = Action-Stop;         continue }
    if ($ch -match '^[Rr]$') { $flash = Action-Restart;      continue }
    if ($ch -match '^[Ll]$') { $flash = Action-Logs;         continue }
    if ($ch -match '^[Cc]$') { $flash = Action-Console;      continue }
    if ($ch -match '^[Nn]$') { $flash = Action-NewWorld;     continue }
    if ($ch -match '^[Dd]$') { $flash = Action-DeleteWorld;  continue }
    if ($ch -match '^[Tt]$') { $flash = Action-ResetWorld;   continue }

    if ($ch -match '^[1-9]$') {
        $d = Get-DashboardData
        $idx = [int]("$ch") - 1
        if ($idx -ge 0 -and $idx -lt $d.Worlds.Count) {
            $flash = Action-SwitchWorld -WorldName $d.Worlds[$idx]
        } else {
            $flash = "Out of range."
        }
        continue
    }
    # Any other key: just refresh (flash stays empty)
}