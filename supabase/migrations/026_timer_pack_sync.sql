-- Let the validated Pack Mode RPC acquire its race-session row lock for timers.
-- The function keeps its existing application-role guard and all event context
-- validation. Timer accounts still receive no direct race_sessions write policy.

alter function public.record_pack_split_events(uuid, jsonb, text)
    security definer;
