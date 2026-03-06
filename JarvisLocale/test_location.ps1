Add-Type -AssemblyName System.Device
$GeoWatcher = New-Object System.Device.Location.GeoCoordinateWatcher
$GeoWatcher.Start()
while (($GeoWatcher.Status -ne 'Ready') -and ($GeoWatcher.Permission -ne 'Denied')) {
    Start-Sleep -Milliseconds 100
}
if ($GeoWatcher.Permission -eq 'Denied'){
    Write-Output "Denied"
} else {
    if ($GeoWatcher.Status -eq 'Ready') {
        Write-Output "$($GeoWatcher.Position.Location.Latitude),$($GeoWatcher.Position.Location.Longitude)"
    } else {
        Write-Output "NotReady"
    }
}
$GeoWatcher.Stop()
