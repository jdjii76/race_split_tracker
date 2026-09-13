-- Application-level single-school branding settings. Image bytes live in Storage.
create table if not exists public.school_profiles (
    id uuid primary key default gen_random_uuid(),
    profile_key text not null unique,
    school_name text not null check (length(trim(school_name)) > 0),
    short_name text not null check (length(trim(short_name)) > 0),
    program_name text, mascot text, city text, state text, app_title text,
    primary_color text not null check (primary_color ~ '^#[0-9A-Fa-f]{6}$'),
    secondary_color text not null check (secondary_color ~ '^#[0-9A-Fa-f]{6}$'),
    accent_color text not null check (accent_color ~ '^#[0-9A-Fa-f]{6}$'),
    text_on_primary text not null check (text_on_primary ~ '^#[0-9A-Fa-f]{6}$'),
    logo_path text, compact_logo_path text,
    header_style text not null default 'standard' check (header_style in ('standard','logo_left','compact','text_only')),
    show_logo_on_dashboard boolean not null default true,
    show_logo_on_timing boolean not null default true,
    include_branding_on_exports boolean not null default true,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);
alter table public.school_profiles enable row level security;
-- DEVELOPMENT ONLY: the in-app passcode is a UI gate, not database authorization.
-- Replace with authenticated administrator policies before public deployment.
do $$ begin
    if not exists (select 1 from pg_policies where schemaname='public' and tablename='school_profiles' and policyname='dev_anon_all_school_profiles') then
        create policy dev_anon_all_school_profiles on public.school_profiles for all to anon using (true) with check (true);
    end if;
end $$;
