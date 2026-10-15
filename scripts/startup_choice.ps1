function Select-StartupResearch([int]$BackendPort) {
    $startup = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/startup" -TimeoutSec 10
    if ($startup.answer) {
        if ($startup.answer -eq 'N') { Write-Host 'Opening the research home page.' }
        else { Write-Host "Selected research task: $($startup.selected_run_id)" }
        return
    }
    if (-not $startup.candidate) { return }
    Write-Host "Found latest unfinished research: $($startup.candidate.company)"
    Write-Host "Created: $($startup.candidate.created_at); stage: $($startup.candidate.stage); status: $($startup.candidate.status)"
    Write-Host 'Y: continue this task using its latest saved progress.'
    Write-Host 'N: return to the research home page; keep the old records.'
    if (-not $startup.candidate.can_continue) { Write-Host $startup.candidate.reason }
    do {
        $answer = (Read-Host 'Continue the latest unfinished research? [Y/N]').Trim().ToUpperInvariant()
        if ($answer -notin @('Y','N')) {
            Write-Host 'Please enter Y or N.'
            continue
        }
        $body = @{run_id=$startup.candidate.run_id;session_id=$startup.session_id;answer=$answer} | ConvertTo-Json -Compress
        try {
            $selection = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$BackendPort/api/startup/decision" -ContentType 'application/json' -Body $body -TimeoutSec 30
            if ($selection.answer -eq 'N') { Write-Host 'Opening the research home page.' }
            else { Write-Host "Selected research task: $($selection.selected_run_id)" }
            break
        } catch {
            Write-Warning "Cannot continue safely: $($_.ErrorDetails.Message)"
            Write-Host 'Choose N to return to the home page without deleting the old records.'
        }
    } while ($true)
}
