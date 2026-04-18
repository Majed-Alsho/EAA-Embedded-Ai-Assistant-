$file = "C:\Users\offic\EAA\eaa_agent_loop_v3.py" 
$content = Get-Content $file -Raw -Encoding UTF8 
ECHO is on.
                # VRAM GUARD: Free cached VRAM before generation 
                try: 
                    import torch 
                    if torch.cuda.is_available(): 
                        gc.collect() 
                        torch.cuda.empty_cache() 
                        torch.cuda.synchronize() 
                except Exception: 
                    pass 
ECHO is on.
                # VRAM GUARD: Aggressive cleanup before generation 
                # Uses full _free_vram() to also clear brain_manager cached tensor refs 
                self._free_vram() 
ECHO is on.
if ($content.Contains($old)) { 
    $content = $content.Replace($old, $new, 1) 
    Set-Content $file -Value $content -Encoding UTF8 -NoNewline 
    Write-Output "PATCH APPLIED" 
} else { 
    Write-Output "ERROR: Old guard not found" 
} 
