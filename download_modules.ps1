$modules = @(
    "eaa_multimodal_tools.py",
    "eaa_document_tools.py", 
    "eaa_system_tools.py",
    "eaa_code_tools.py",
    "eaa_browser_tools.py",
    "eaa_communication_tools.py",
    "eaa_memory_enhanced.py",
    "eaa_data_tools.py",
    "eaa_audio_video_tools.py",
    "eaa_scheduler_tools.py",
    "eaa_tool_executor.py"
)

$baseDir = "C:\Users\offic\EAA"
$baseUrl = "http://8.218.51.189:8899"
$python = "$baseDir\.venv-hf\Scripts\python.exe"

foreach ($mod in $modules) {
    $url = "$baseUrl/$mod"
    $dest = "$baseDir\$mod"
    Write-Host "Downloading $mod..."
    try {
        # Try PowerShell download first
        Invoke-WebRequest -Uri $url -OutFile $dest -TimeoutSec 30 -ErrorAction Stop
        $size = (Get-Item $dest).Length
        Write-Host "  OK - $size bytes"
    } catch {
        Write-Host "  PS failed: $_, trying Python..."
        try {
            & $python -c "import urllib.request; urllib.request.urlretrieve('$url', r'$dest')"
            $size = (Get-Item $dest).Length
            Write-Host "  OK - $size bytes"
        } catch {
            Write-Host "  FAILED: $_"
        }
    }
}
Write-Host "`nDone! Checking all files..."
Get-ChildItem "$baseDir\eaa_*.py" | Select-Object Name, Length | Format-Table -AutoSize
