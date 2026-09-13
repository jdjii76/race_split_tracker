-- Allow the shared timer account to use the existing validated race-start RPC.
-- The function checks the application role, serializes by race, and only creates
-- or resumes the single active session with its immutable checkpoint snapshot.
-- Timers still receive no direct INSERT or UPDATE policy on lifecycle tables.

alter function public.get_or_create_active_race_session(uuid, jsonb)
    security definer;
