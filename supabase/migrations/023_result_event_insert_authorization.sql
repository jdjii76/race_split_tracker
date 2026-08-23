-- Complete the ResultEvent SECURITY INVOKER authorization boundary.
grant select, insert on table public.result_events to authenticated;

drop policy if exists result_events_staff_insert on public.result_events;
create policy result_events_staff_insert
on public.result_events
for insert
to authenticated
with check (public.has_app_role(array['coach','admin']));

notify pgrst, 'reload schema';
