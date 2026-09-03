# Pickerbot Mini SSH connect helper - kulcsos, jelszo nelkuli belepes
# Usage: .\connect.ps1  vagy  .\connect.ps1 "hostname && uname -a"
param(
    [string]$Command = ""
)

$ip = "192.168.0.100"
$user = "wheeltec"
$keyPath = "$env:USERPROFILE\.ssh\pickerbot_mini"

if (-not (Test-Path $keyPath)) {
    Write-Error "SSH kulcs nem talalhato: $keyPath"
    exit 1
}

if ($Command -eq "") {
    ssh -i $keyPath "$user@$ip"
} else {
    ssh -i $keyPath "$user@$ip" $Command
}
