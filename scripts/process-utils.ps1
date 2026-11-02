function Test-PilotProcess($Candidate, $State) {
    if (!$Candidate) { return $false }
    if ($State.startTicks) {
        return $Candidate.StartTime.ToUniversalTime().Ticks.ToString() -eq $State.startTicks
    }
    return $Candidate.StartTime.ToUniversalTime().Ticks -eq ([datetime]$State.startTime).ToUniversalTime().Ticks
}
