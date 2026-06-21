-- Migration 004 : amélioration extraction audio
-- Ajoute le débit et le profil par piste audio (valeurs semicolonne-délimitées)

ALTER TABLE video_metadata
  ADD COLUMN IF NOT EXISTS audio_bitrates TEXT,
  ADD COLUMN IF NOT EXISTS audio_profiles TEXT;
