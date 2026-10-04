# TEST D RESULT ARTIFACT — live product proof

Seat: Nico (Space Bunny)
Date: 2026-10-03

This item exists to prove that a live queue item survives the running
VoiceBridge's 30-second refresh cycle. Under the legacy panel it would have
been silently archived within one refresh, because the age rule archived
anything older than "yesterday".

Its `created_at` is deliberately backdated so the old rule would have caught
it immediately. Under the rebuilt panel it must remain ACTIVE.