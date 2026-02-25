-- Fix avatar paths: add 'images/avatars/' prefix to paths that are missing it
-- This fixes custom avatars stored as 'custom/...' instead of 'images/avatars/custom/...'
-- and default avatars stored as 'default_avatars/...' instead of 'images/avatars/default_avatars/...'

UPDATE users
SET avatar_path = CONCAT('images/avatars/', avatar_path)
WHERE avatar_path IS NOT NULL
  AND avatar_path != ''
  AND avatar_path NOT LIKE 'images/avatars/%';
