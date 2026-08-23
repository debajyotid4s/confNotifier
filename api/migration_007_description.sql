-- Add conference overview/description field (R9: Gemini returns <=200 word overview).
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS description TEXT;
