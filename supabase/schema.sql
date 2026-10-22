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

-- ============================================================================
-- 9. МЕССЕНДЖЕР: личные диалоги, группы, реакции.
--    Переписка видна только её участникам — даже из БД чужие чаты не вытащить.
-- ============================================================================

-- Персонаж-аватар участника (ключ из index.html: kazar, alice, misha, diana,
-- artemiy, marina, khariton, natasha, yulia, nikita, lena, kira, dima,
-- sasha, vitya, vova, jenya). Пример:
-- update public.members set char = 'kazar' where email = 'primer@example.com';
alter table public.members add column if not exists char text;

-- Участники клуба видят адресную книгу (нужно, чтобы добавлять друзей в чаты)
drop policy if exists "member sees self" on public.members;
do $$ begin
  create policy "members read" on public.members
    for select to authenticated using (public.is_member());
exception when duplicate_object then null; end $$;

create table if not exists public.conversations (
  id         uuid primary key default gen_random_uuid(),
  kind       text not null check (kind in ('dm','group')),
  title      text,
  pair_key   text unique,               -- 'a@x|b@x' — защита от дублей личных чатов
  created_by text,
  created_at timestamptz not null default now()
);
alter table public.conversations enable row level security;

create table if not exists public.conversation_members (
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  email           text not null,
  joined_at       timestamptz not null default now(),
  primary key (conversation_id, email)
);
alter table public.conversation_members enable row level security;

create table if not exists public.messages (
  id             bigint generated always as identity primary key,
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  author_email   text not null,
  author_name    text not null,
  text           text not null,
  ts             bigint not null default (extract(epoch from now()) * 1000)::bigint
);
alter table public.messages enable row level security;

create table if not exists public.message_reactions (
  message_id bigint not null references public.messages(id) on delete cascade,
  email      text not null,
  emoji      text not null,
  primary key (message_id, email, emoji)
);
alter table public.message_reactions enable row level security;

-- «я в этой переписке?» — security definer, чтобы политика не ссылалась на
-- саму себя и не зацикливалась
create or replace function public.in_conversation(cid uuid) returns boolean
language sql stable security definer set search_path = public as
$$ select exists (
     select 1 from public.conversation_members
     where conversation_id = cid
       and lower(email) = lower(auth.jwt() ->> 'email')
   ) $$;

do $$ begin
  create policy "conv read" on public.conversations
    for select to authenticated
    using (public.is_member() and public.in_conversation(id));
  create policy "conv create" on public.conversations
    for insert to authenticated
    with check (public.is_member() and created_by = auth.jwt() ->> 'email');
  create policy "conv del own" on public.conversations
    for delete to authenticated using (created_by = auth.jwt() ->> 'email');
exception when duplicate_object then null; end $$;

do $$ begin
  create policy "cm read" on public.conversation_members
    for select to authenticated
    using (public.is_member() and public.in_conversation(conversation_id));
  create policy "cm add" on public.conversation_members
    for insert to authenticated
    with check (public.is_member() and (
      public.in_conversation(conversation_id) or
      exists (select 1 from public.conversations c
              where c.id = conversation_id
                and c.created_by = auth.jwt() ->> 'email')));
  create policy "cm del self" on public.conversation_members
    for delete to authenticated
    using (lower(email) = lower(auth.jwt() ->> 'email'));
exception when duplicate_object then null; end $$;

do $$ begin
  create policy "msg read" on public.messages
    for select to authenticated
    using (public.is_member() and public.in_conversation(conversation_id));
  create policy "msg add" on public.messages
    for insert to authenticated
    with check (public.is_member() and public.in_conversation(conversation_id)
                and author_email = auth.jwt() ->> 'email');
  create policy "msg del own" on public.messages
    for delete to authenticated using (author_email = auth.jwt() ->> 'email');
exception when duplicate_object then null; end $$;

do $$ begin
  create policy "rx read" on public.message_reactions
    for select to authenticated
    using (public.is_member() and exists (
      select 1 from public.messages m
      where m.id = message_id and public.in_conversation(m.conversation_id)));
  create policy "rx add" on public.message_reactions
    for insert to authenticated
    with check (lower(email) = lower(auth.jwt() ->> 'email') and exists (
      select 1 from public.messages m
      where m.id = message_id and public.in_conversation(m.conversation_id)));
  create policy "rx del own" on public.message_reactions
    for delete to authenticated
    using (lower(email) = lower(auth.jwt() ->> 'email'));
exception when duplicate_object then null; end $$;

do $$ begin alter publication supabase_realtime add table public.conversations;        exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.conversation_members; exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.messages;             exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.message_reactions;    exception when duplicate_object then null; end $$;

-- ============================================================================
-- 10. ДНИ РОЖДЕНИЯ: дата в members + возможность указать свою дату
-- ============================================================================
alter table public.members add column if not exists birthday date;

do $$ begin
  create policy "member update self" on public.members
    for update to authenticated
    using (lower(email) = lower(auth.jwt() ->> 'email'))
    with check (lower(email) = lower(auth.jwt() ->> 'email'));
exception when duplicate_object then null; end $$;

-- ============================================================================
-- 11. ЧЕЛЛЕНДЖИ: вызовы участникам + отметки «я в деле»
-- ============================================================================
create table if not exists public.challenges (
  id    bigint generated always as identity primary key,
  title text not null,
  text  text,
  until date,
  by    text,
  ts    timestamptz not null default now()
);
alter table public.challenges enable row level security;
do $$ begin
  create policy "chal read" on public.challenges
    for select to authenticated using (public.is_member());
  create policy "chal add" on public.challenges
    for insert to authenticated with check (public.is_member());
  create policy "chal del own" on public.challenges
    for delete to authenticated using (by = auth.jwt() ->> 'email');
exception when duplicate_object then null; end $$;

create table if not exists public.challenge_join (
  challenge_id bigint not null references public.challenges(id) on delete cascade,
  email        text not null,
  primary key (challenge_id, email)
);
alter table public.challenge_join enable row level security;
do $$ begin
  create policy "cjoin read" on public.challenge_join
    for select to authenticated using (public.is_member());
  create policy "cjoin add" on public.challenge_join
    for insert to authenticated
    with check (public.is_member() and lower(email) = lower(auth.jwt() ->> 'email'));
  create policy "cjoin del own" on public.challenge_join
    for delete to authenticated
    using (lower(email) = lower(auth.jwt() ->> 'email'));
exception when duplicate_object then null; end $$;

do $$ begin alter publication supabase_realtime add table public.challenges;     exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.challenge_join; exception when duplicate_object then null; end $$;

-- ============================================================================
-- 12. ЧЕКИ: общие покупки — фото, сумма, кто платил
-- ============================================================================
create table if not exists public.receipts (
  id     bigint generated always as identity primary key,
  amount numeric(10,2) not null check (amount >= 0),
  note   text,
  path   text,                -- фото чека в приватном бакете photos (receipts/…)
  by     text not null,
  ts     bigint not null default (extract(epoch from now()) * 1000)::bigint
);
alter table public.receipts enable row level security;
do $$ begin
  create policy "rc read" on public.receipts
    for select to authenticated using (public.is_member());
  create policy "rc add" on public.receipts
    for insert to authenticated with check (public.is_member());
  create policy "rc del own" on public.receipts
    for delete to authenticated using (by = auth.jwt() ->> 'email');
exception when duplicate_object then null; end $$;

do $$ begin alter publication supabase_realtime add table public.receipts; exception when duplicate_object then null; end $$;
