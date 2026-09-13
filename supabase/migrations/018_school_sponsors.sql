-- Additive school-wide sponsor management and privacy-safe public display.
create table if not exists public.school_sponsors (
    id uuid primary key default gen_random_uuid(),
    school_profile_id uuid not null references public.school_profiles(id) on delete cascade,
    name text not null check (length(trim(name)) > 0),
    logo_path text not null check (length(trim(logo_path)) > 0),
    website_url text,
    display_order integer not null default 0 check (display_order >= 0),
    is_active boolean not null default true,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);
create index if not exists idx_school_sponsors_school on public.school_sponsors(school_profile_id);
create index if not exists idx_school_sponsors_active on public.school_sponsors(is_active);
create index if not exists idx_school_sponsors_display_order on public.school_sponsors(display_order);
create index if not exists idx_school_sponsors_active_order on public.school_sponsors(school_profile_id, is_active, display_order);
alter table public.school_sponsors enable row level security;
create policy app_admin_school_sponsors on public.school_sponsors for all to authenticated
    using (public.has_app_role(array['admin'])) with check (public.has_app_role(array['admin']));
grant select, insert, update, delete on public.school_sponsors to authenticated;
revoke all on public.school_sponsors from anon;

create or replace view public.spectator_sponsors with (security_barrier=true) as
select ss.id, ss.school_profile_id, sp.profile_key, ss.name, ss.logo_path, ss.website_url, ss.display_order, ss.is_active
from public.school_sponsors ss join public.school_profiles sp on sp.id = ss.school_profile_id
where ss.is_active;
grant select on public.spectator_sponsors to anon, authenticated;

-- Reuse the existing public branding bucket. Sponsor objects are grouped under
-- sponsors/{school_profile_id}/{sponsor_id}/logo.ext.
insert into storage.buckets (id, name, public)
values ('branding', 'branding', true)
on conflict (id) do update set public = true;

drop policy if exists public_read_branding_assets on storage.objects;
create policy public_read_branding_assets on storage.objects for select to anon, authenticated
    using (bucket_id = 'branding');
drop policy if exists admin_manage_branding_assets on storage.objects;
create policy admin_manage_branding_assets on storage.objects for all to authenticated
    using (bucket_id = 'branding' and public.has_app_role(array['admin']))
    with check (bucket_id = 'branding' and public.has_app_role(array['admin']));
