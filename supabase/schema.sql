-- ============================================================================
--  Dear Friends · настройка приватного клуба на Supabase
--  Куда: Supabase → SQL Editor → New query → вставить ВЕСЬ файл → Run
--  Повторный запуск безопасен: существующие объекты не пересоздаются.
-- ============================================================================

-- 1. УЧАСТНИКИ КЛУБА (белый список email — «вход для своих»)
create table if not exists public.members (
  email text primary key,
  name  text,
  created_at timestamptz not null default now()
);
alter table public.members enable row level security;

-- 2. Функция «я участник?» — на неё опираются все правила доступа ниже.
--    Человек может войти с любым email, но данные видит только тот,
--    чей email добавлен в members.
create or replace function public.is_member() returns boolean
language sql stable security definer set search_path = public as
$$ select exists (
     select 1 from public.members
     where lower(email) = lower(auth.jwt() ->> 'email')
   ) $$;

-- Каждый видит только свою строку в members (чужие почты не светятся).
do $$ begin
  create policy "member sees self" on public.members
    for select to authenticated
    using (lower(email) = lower(auth.jwt() ->> 'email'));
exception when duplicate_object then null; end $$;

-- 3. АНОНСЫ встреч
create table if not exists public.events (
  id    bigint generated always as identity primary key,
  title text not null,
  date  date not null,
  place text,
  by    text,
  created_at timestamptz not null default now()
);
alter table public.events enable row level security;
do $$ begin
  create policy "events read" on public.events
    for select to authenticated using (public.is_member());
  create policy "events add" on public.events
    for insert to authenticated with check (public.is_member());
  create policy "events del own" on public.events
    for delete to authenticated using (by = auth.jwt() ->> 'email');
exception when duplicate_object then null; end $$;

-- 4. ЧАТ
create table if not exists public.chat (
  id   bigint generated always as identity primary key,
  name text not null,
  text text not null,
  ts   bigint not null default (extract(epoch from now()) * 1000)::bigint
);
alter table public.chat enable row level security;
do $$ begin
  create policy "chat read" on public.chat
    for select to authenticated using (public.is_member());
  create policy "chat add" on public.chat
    for insert to authenticated with check (public.is_member());
exception when duplicate_object then null; end $$;

-- 5. ПОМОЩЬ И СБОРЫ: просьбы + отклики «могу помочь»
create table if not exists public.help (
  id     bigint generated always as identity primary key,
  title  text not null,
  text   text,
  urgent boolean not null default false,
  by     text,
  ts     timestamptz not null default now()
);
alter table public.help enable row level security;
do $$ begin
  create policy "help read" on public.help
    for select to authenticated using (public.is_member());
  create policy "help add" on public.help
    for insert to authenticated with check (public.is_member());
  create policy "help del own" on public.help
    for delete to authenticated using (by = auth.jwt() ->> 'email');
exception when duplicate_object then null; end $$;

create table if not exists public.help_resp (
  help_id bigint not null references public.help(id) on delete cascade,
  email   text not null,
  primary key (help_id, email)
);
alter table public.help_resp enable row level security;
do $$ begin
  create policy "resp read" on public.help_resp
    for select to authenticated using (public.is_member());
  create policy "resp add own" on public.help_resp
    for insert to authenticated with check (
      public.is_member() and lower(email) = lower(auth.jwt() ->> 'email'));
  create policy "resp del own" on public.help_resp
    for delete to authenticated using (lower(email) = lower(auth.jwt() ->> 'email'));
exception when duplicate_object then null; end $$;

-- 6. ФОТО: приватный бакет хранилища + таблица-учёт
create table if not exists public.photos (
  id   bigint generated always as identity primary key,
  path text not null,
  by   text,
  ts   bigint not null default (extract(epoch from now()) * 1000)::bigint
);
alter table public.photos enable row level security;
do $$ begin
  create policy "photos read" on public.photos
    for select to authenticated using (public.is_member());
  create policy "photos add" on public.photos
    for insert to authenticated with check (public.is_member());
exception when duplicate_object then null; end $$;

insert into storage.buckets (id, name, public)
values ('photos', 'photos', false)
on conflict (id) do nothing;

do $$ begin
  create policy "bucket photos read" on storage.objects
    for select to authenticated
    using (bucket_id = 'photos' and public.is_member());
  create policy "bucket photos write" on storage.objects
    for insert to authenticated
    with check (bucket_id = 'photos' and public.is_member());
exception when duplicate_object then null; end $$;

-- 7. ОНЛАЙН-ОБНОВЛЕНИЯ (чат/события появляются без перезагрузки)
do $$ begin alter publication supabase_realtime add table public.chat;   exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.events; exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.help;   exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.photos; exception when duplicate_object then null; end $$;

-- 8. ПРИГЛАСИТЬ ДРУЗЕЙ: подставьте настоящие почты и выполните.
--    Формат: ('email', 'имя как в чате')
insert into public.members (email, name) values
  ('primer@example.com', 'Пример')
on conflict (email) do update set name = excluded.name;
