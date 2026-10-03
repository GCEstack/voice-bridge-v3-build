@{
  schema = "voicebridge.queue.local_state"
  dismissed = @()
  updated_at = "2026-10-02T00:00:00"
} | ConvertTo-Json | Set-Content "C:\Users\Dekan AI Brother\GCE_DON\voice-bridge\queue_local.json"