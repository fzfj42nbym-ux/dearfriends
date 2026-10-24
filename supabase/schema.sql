-- ============================================================================
--  Dear Friends · настройка приватного клуба на Supabase
--  Куда: Supabase → SQL Editor → New query → вставить ВЕСЬ файл → Run
--  Повторный запуск сохраняет данные и обновляет правила доступа.
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

-- Создание переписки и первого состава — только атомарно через RPC ниже.
-- Иначе RETURNING упирается в приватную read-политику до добавления участников.
drop policy if exists "conv create" on public.conversations;
do $$ begin
  create policy "conv read" on public.conversations
    for select to authenticated
    using (public.is_member() and public.in_conversation(id));
  create policy "conv del own" on public.conversations
    for delete to authenticated using (created_by = auth.jwt() ->> 'email');
exception when duplicate_object then null; end $$;

drop policy if exists "cm add" on public.conversation_members;
do $$ begin
  create policy "cm read" on public.conversation_members
    for select to authenticated
    using (public.is_member() and public.in_conversation(conversation_id));
  create policy "cm del self" on public.conversation_members
    for delete to authenticated
    using (lower(email) = lower(auth.jwt() ->> 'email'));
exception when duplicate_object then null; end $$;

-- RPC создаёт переписку и всех участников в одной транзакции. Публичный клиент
-- не назначает created_by/pair_key и не может добавить себя в чужую переписку.
create or replace function public.create_conversation(
  p_kind text,
  p_title text default null,
  p_emails text[] default '{}'::text[]
) returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  caller_email text := lower(btrim(coalesce(auth.jwt() ->> 'email', '')));
  participant_emails text[];
  existing_emails text[];
  result_id uuid;
  dm_key text;
  group_title text;
begin
  if caller_email = '' or not public.is_member() then
    raise exception using errcode = '42501', message = 'Вход доступен только участникам клуба';
  end if;
  if p_kind is null or p_kind not in ('dm', 'group') then
    raise exception using errcode = '22023', message = 'Неизвестный вид переписки';
  end if;
  if coalesce(cardinality(p_emails), 0) > 99 or exists (
    select 1 from unnest(p_emails) as requested(email)
    where email is null or btrim(email) = ''
  ) then
    raise exception using errcode = '22023', message = 'Некорректный список участников';
  end if;

  select array_agg(email order by email) into participant_emails
  from (
    select distinct lower(btrim(email)) as email
    from unnest(array_append(coalesce(p_emails, '{}'::text[]), caller_email)) as requested(email)
  ) as normalized;

  if cardinality(participant_emails) < 2 or
     (p_kind = 'dm' and cardinality(participant_emails) <> 2) then
    raise exception using errcode = '22023', message = 'Выберите участников переписки';
  end if;
  if exists (
    select 1 from unnest(participant_emails) as requested(email)
    where not exists (
      select 1 from public.members as member where lower(member.email) = requested.email
    )
  ) then
    raise exception using errcode = '22023', message = 'Можно пригласить только участников клуба';
  end if;

  if p_kind = 'group' then
    group_title := btrim(coalesce(p_title, ''));
    if char_length(group_title) not between 1 and 80 then
      raise exception using errcode = '22023', message = 'Название группы: от 1 до 80 символов';
    end if;
  else
    dm_key := array_to_string(participant_emails, '|');
  end if;

  insert into public.conversations (kind, title, pair_key, created_by)
  values (p_kind, group_title, dm_key, caller_email)
  on conflict (pair_key) do nothing
  returning id into result_id;

  if result_id is null then
    -- Конкурирующий запрос мог уже создать тот же DM. Уникальный pair_key
    -- сериализует вставки; чужую переписку этот путь не раскрывает.
    select conversation.id into result_id
    from public.conversations as conversation
    where conversation.pair_key = dm_key and conversation.kind = 'dm'
      and public.in_conversation(conversation.id);
    if result_id is null then
      raise exception using errcode = '42501', message = 'Эта переписка недоступна';
    end if;
    select array_agg(distinct lower(member.email) order by lower(member.email))
    into existing_emails
    from public.conversation_members as member
    where member.conversation_id = result_id;
    if existing_emails is distinct from participant_emails then
      raise exception using errcode = '42501', message = 'Состав переписки не совпадает';
    end if;
    return result_id;
  end if;

  insert into public.conversation_members (conversation_id, email)
  select result_id, email from unnest(participant_emails) as participant(email);
  return result_id;
end;
$$;
revoke all on function public.create_conversation(text, text, text[]) from public, anon;
grant execute on function public.create_conversation(text, text, text[]) to authenticated;

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
-- 10. БИБЛИОТЕКА: фильмы, сериалы, книги и игры; оценки и общая полка.
--     Каталог приватный. Каждую оценку меняет только её автор, выдача экземпляра
--     проходит через атомарный RPC: одну книгу нельзя одновременно взять вдвоём.
-- ============================================================================
create table if not exists public.library_items (
  id uuid primary key default gen_random_uuid(),
  kind text not null,
  title text not null check (title = btrim(title) and char_length(title) between 1 and 120),
  creator text not null default '' check (char_length(creator) <= 120),
  blurb text not null default '' check (char_length(blurb) <= 600),
  genre text not null default '' check (char_length(genre) <= 40),
  duration_minutes integer check (duration_minutes between 1 and 10000),
  players_min integer check (players_min between 1 and 30),
  players_max integer check (players_max between 1 and 30),
  shareable boolean not null default false,
  -- История каталога остаётся при выходе автора из клуба; вставку проверяет RLS.
  added_by text not null,
  created_at timestamptz not null default now(),
  check (players_min is null or players_max is null or players_max >= players_min)
);
alter table public.library_items enable row level security;

-- Обновление уже установленной библиотеки из трёх категорий. CREATE IF NOT
-- EXISTS не меняет прежний CHECK, поэтому заменяем его явно и атомарно.
-- Старый CHECK выдачи получил имя library_items_check; проверка колонок
-- отличает его от одноимённого ограничения диапазона игроков в новой таблице.
do $$ begin
  if exists (
    select 1 from pg_catalog.pg_constraint as restriction
    where restriction.conrelid = 'public.library_items'::regclass
      and restriction.conname = 'library_items_check'
      and restriction.contype = 'c'
      and cardinality(restriction.conkey) = 2
      and restriction.conkey @> array[
        (select attnum from pg_catalog.pg_attribute
         where attrelid = 'public.library_items'::regclass and attname = 'kind'),
        (select attnum from pg_catalog.pg_attribute
         where attrelid = 'public.library_items'::regclass and attname = 'shareable')
      ]
  ) then
    alter table public.library_items drop constraint library_items_check;
  end if;
  alter table public.library_items
    drop constraint if exists library_items_kind_check,
    drop constraint if exists library_items_shareable_check,
    add constraint library_items_kind_check
      check (kind in ('movie', 'series', 'book', 'game')),
    add constraint library_items_shareable_check
      check (not shareable or kind in ('book', 'game'));
end $$;

create table if not exists public.library_marks (
  item_id uuid not null references public.library_items(id) on delete cascade,
  email text not null references public.members(email) on delete cascade,
  status text check (status in ('want', 'doing', 'done')),
  rating integer check (rating between 1 and 5),
  review text not null default '' check (char_length(review) <= 600),
  updated_at timestamptz not null default now(),
  primary key (item_id, email)
);
-- Даже при случайных двух записях email в allowlist регистр не удваивает голос.
create unique index if not exists library_marks_one_vote
  on public.library_marks (item_id, lower(email));
alter table public.library_marks enable row level security;

create table if not exists public.library_loans (
  item_id uuid primary key references public.library_items(id) on delete cascade,
  borrower_email text not null references public.members(email) on delete cascade,
  borrowed_at timestamptz not null default now()
);
alter table public.library_loans enable row level security;

-- Явные grants не зависят от Supabase default privileges. Запись выдач закрыта
-- даже при прежних широких grants: изменять её может только RPC ниже.
revoke all on public.library_items, public.library_marks, public.library_loans
  from public, anon, authenticated;
grant select, insert on public.library_items to authenticated;
grant select, insert, update, delete on public.library_marks to authenticated;
grant select on public.library_loans to authenticated;

drop policy if exists "library items read" on public.library_items;
create policy "library items read" on public.library_items
  for select to authenticated using (public.is_member());
drop policy if exists "library items add own" on public.library_items;
create policy "library items add own" on public.library_items
  for insert to authenticated with check (
    public.is_member() and lower(added_by) = lower(auth.jwt() ->> 'email'));

drop policy if exists "library marks read" on public.library_marks;
create policy "library marks read" on public.library_marks
  for select to authenticated using (public.is_member());
drop policy if exists "library marks add own" on public.library_marks;
create policy "library marks add own" on public.library_marks
  for insert to authenticated with check (
    public.is_member() and lower(email) = lower(auth.jwt() ->> 'email'));
drop policy if exists "library marks update own" on public.library_marks;
create policy "library marks update own" on public.library_marks
  for update to authenticated
  using (public.is_member() and lower(email) = lower(auth.jwt() ->> 'email'))
  with check (public.is_member() and lower(email) = lower(auth.jwt() ->> 'email'));
drop policy if exists "library marks delete own" on public.library_marks;
create policy "library marks delete own" on public.library_marks
  for delete to authenticated
  using (public.is_member() and lower(email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "library loans read" on public.library_loans;
create policy "library loans read" on public.library_loans
  for select to authenticated using (public.is_member());

create or replace function public.library_mark_timestamp() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := pg_catalog.clock_timestamp();
  return new;
end;
$$;
drop trigger if exists library_mark_timestamp on public.library_marks;
create trigger library_mark_timestamp before update on public.library_marks
  for each row execute function public.library_mark_timestamp();

create or replace function public.borrow_library_item(p_item uuid, p_action text)
returns void language plpgsql security definer set search_path = '' as $$
declare
  caller_email text;
  selected_item public.library_items%rowtype;
  holder_email text;
begin
  if not public.is_member() then
    raise exception using errcode = '42501', message = 'Библиотека доступна только участникам клуба';
  end if;
  select member.email into caller_email from public.members as member
    where lower(member.email) = lower(auth.jwt() ->> 'email')
    order by member.email limit 1;
  if caller_email is null then
    raise exception using errcode = '42501', message = 'Не удалось определить участника';
  end if;
  if p_action is null or p_action not in ('borrow', 'return') or p_item is null then
    raise exception using errcode = '22023', message = 'Неизвестное действие с экземпляром';
  end if;

  -- Lock общей карточки сериализует borrow и return, в том числе когда выдачи
  -- ещё нет. Уникального item_id недостаточно для безопасной пары borrow/return.
  select * into selected_item from public.library_items where id = p_item for update;
  if not found then
    raise exception using errcode = '22023', message = 'Карточка не найдена';
  end if;
  if not selected_item.shareable or selected_item.kind not in ('book', 'game') then
    raise exception using errcode = '55000', message = 'Этот экземпляр не на общей полке';
  end if;
  select borrower_email into holder_email from public.library_loans where item_id = p_item;
  if p_action = 'borrow' then
    if holder_email is not null then
      raise exception using errcode = '55000', message = 'Экземпляр уже у друга';
    end if;
    insert into public.library_loans(item_id, borrower_email) values (p_item, caller_email);
  else
    if holder_email is null then
      raise exception using errcode = '55000', message = 'Экземпляр уже на полке';
    end if;
    if lower(holder_email) <> lower(caller_email)
       and lower(selected_item.added_by) <> lower(caller_email) then
      raise exception using errcode = '42501', message = 'Вернуть может получатель или владелец экземпляра';
    end if;
    delete from public.library_loans where item_id = p_item;
  end if;
end;
$$;
revoke all on function public.borrow_library_item(uuid, text) from public, anon;
grant execute on function public.borrow_library_item(uuid, text) to authenticated;

do $$ begin alter publication supabase_realtime add table public.library_items; exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.library_marks; exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.library_loans; exception when duplicate_object then null; end $$;

-- ============================================================================
-- 11. ДНИ РОЖДЕНИЯ: совместимо с GitHub main; участник меняет только свою дату.
--     RLS ограничивает строку, column grant — поле. Имя, почта и герой этим
--     экраном не редактируются, даже при прежних широких Supabase grants.
-- ============================================================================
alter table public.members add column if not exists birthday date;
revoke update on public.members from public, anon, authenticated;
revoke update (email, name, created_at, char, birthday) on public.members
  from public, anon, authenticated;
grant select on public.members to authenticated;
grant update (birthday) on public.members to authenticated;

drop policy if exists "member update self" on public.members;
create policy "member update self" on public.members
  for update to authenticated
  using (public.is_member() and lower(email) = lower(auth.jwt() ->> 'email'))
  with check (public.is_member() and lower(email) = lower(auth.jwt() ->> 'email'));

-- ============================================================================
-- 12. ЧЕЛЛЕНДЖИ: вызовы и участие; сохраняем таблицы и ключи уже выпущенного main.
-- ============================================================================
create table if not exists public.challenges (
  id    bigint generated always as identity primary key,
  title text not null,
  text  text,
  until date,
  by    text,
  ts    timestamptz not null default now()
);
create table if not exists public.challenge_join (
  challenge_id bigint not null references public.challenges(id) on delete cascade,
  email text not null,
  primary key (challenge_id, email)
);
alter table public.challenges enable row level security;
alter table public.challenge_join enable row level security;
revoke all on public.challenges, public.challenge_join from public, anon, authenticated;
grant select, insert, delete on public.challenges, public.challenge_join to authenticated;

-- Заменяем старые политики явно: CREATE IF NOT EXISTS не исправляет ранее
-- установленный permissive INSERT, позволявший подставить чужое поле by.
drop policy if exists "chal read" on public.challenges;
create policy "chal read" on public.challenges
  for select to authenticated using (public.is_member());
drop policy if exists "chal add" on public.challenges;
create policy "chal add" on public.challenges
  for insert to authenticated with check (
    public.is_member() and lower(by) = lower(auth.jwt() ->> 'email'));
drop policy if exists "chal del own" on public.challenges;
create policy "chal del own" on public.challenges
  for delete to authenticated using (
    public.is_member() and lower(by) = lower(auth.jwt() ->> 'email'));

drop policy if exists "cjoin read" on public.challenge_join;
create policy "cjoin read" on public.challenge_join
  for select to authenticated using (public.is_member());
drop policy if exists "cjoin add" on public.challenge_join;
create policy "cjoin add" on public.challenge_join
  for insert to authenticated with check (
    public.is_member() and lower(email) = lower(auth.jwt() ->> 'email'));
drop policy if exists "cjoin del own" on public.challenge_join;
create policy "cjoin del own" on public.challenge_join
  for delete to authenticated using (
    public.is_member() and lower(email) = lower(auth.jwt() ->> 'email'));

-- ============================================================================
-- 13. ЧЕКИ: сумма, комментарий и путь к снимку в прежнем приватном бакете photos.
-- ============================================================================
create table if not exists public.receipts (
  id     bigint generated always as identity primary key,
  amount numeric(10,2) not null check (amount >= 0),
  note   text,
  path   text,
  by     text not null,
  ts     bigint not null default (extract(epoch from now()) * 1000)::bigint
);
alter table public.receipts enable row level security;
revoke all on public.receipts from public, anon, authenticated;
grant select, insert, delete on public.receipts to authenticated;

drop policy if exists "rc read" on public.receipts;
create policy "rc read" on public.receipts
  for select to authenticated using (public.is_member());
drop policy if exists "rc add" on public.receipts;
create policy "rc add" on public.receipts
  for insert to authenticated with check (
    public.is_member() and lower(by) = lower(auth.jwt() ->> 'email')
    and amount > 0 and amount < 100000000);
drop policy if exists "rc del own" on public.receipts;
create policy "rc del own" on public.receipts
  for delete to authenticated using (
    public.is_member() and lower(by) = lower(auth.jwt() ->> 'email'));

-- ============================================================================
-- 14. ФОНД: учёт взносов. Это записи клуба, не банковские переводы.
--     В выпущенной схеме amount мог быть отрицательным. Старые движения не
--     удаляем и не добавляем CHECK, который сломал бы повторный запуск.
--     Новый интерфейс и INSERT разрешают только положительный конечный взнос.
-- ============================================================================
create table if not exists public.fund (
  id     bigint generated always as identity primary key,
  amount numeric(10,2) not null,
  note   text,
  by     text not null,
  ts     bigint not null default (extract(epoch from now()) * 1000)::bigint
);
alter table public.fund enable row level security;
revoke all on public.fund from public, anon, authenticated;
grant select, insert, delete on public.fund to authenticated;

drop policy if exists "fund read" on public.fund;
create policy "fund read" on public.fund
  for select to authenticated using (public.is_member());
drop policy if exists "fund add" on public.fund;
create policy "fund add" on public.fund
  for insert to authenticated with check (
    public.is_member() and lower(by) = lower(auth.jwt() ->> 'email')
    and amount > 0 and amount < 100000000);
drop policy if exists "fund del own" on public.fund;
create policy "fund del own" on public.fund
  for delete to authenticated using (
    public.is_member() and lower(by) = lower(auth.jwt() ->> 'email'));

-- Явные privileges identity-последовательностей не зависят от default grants.
do $$ declare
  table_name text;
  identity_sequence text;
begin
  foreach table_name in array array['challenges', 'receipts', 'fund'] loop
    identity_sequence := pg_get_serial_sequence('public.' || table_name, 'id');
    if identity_sequence is not null then
      execute format('revoke all on sequence %s from public, anon, authenticated', identity_sequence);
      execute format('grant usage on sequence %s to authenticated', identity_sequence);
    end if;
  end loop;
end $$;

do $$ begin alter publication supabase_realtime add table public.members; exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.challenges; exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.challenge_join; exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.receipts; exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.fund; exception when duplicate_object then null; end $$;
