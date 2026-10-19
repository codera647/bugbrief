begin;

create table public.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  product_key text not null default 'ledgerflow',
  created_at timestamptz not null default now()
);
create table public.workspace_members (
  workspace_id uuid references public.workspaces(id) on delete cascade,
  user_id uuid references auth.users(id) on delete cascade,
  role text not null check (role in ('viewer','contributor','owner')),
  active boolean not null default true,
  joined_at timestamptz not null default now(),
  primary key(workspace_id,user_id)
);
create table public.tickets (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  created_by uuid not null references auth.users(id),
  operation_id text not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  schema_version text not null default '1.0',
  generation_metadata jsonb not null default '{}',
  source_report text,
  revision integer not null default 1 check (revision > 0),
  status text not null default 'draft' check (status in ('draft','reviewed')),
  reviewed_revision integer,
  reviewed_by uuid references auth.users(id),
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(workspace_id,created_by,operation_id),
  check ((status='draft' and reviewed_revision is null and reviewed_by is null and reviewed_at is null)
    or (status='reviewed' and reviewed_revision=revision and reviewed_by is not null and reviewed_at is not null)),
  check (source_report is null or char_length(source_report) <= 4000)
);
create table public.ticket_revisions (
  ticket_id uuid references public.tickets(id) on delete cascade,
  revision integer not null,
  payload jsonb not null,
  edited_by uuid references auth.users(id),
  created_at timestamptz not null default now(),
  primary key(ticket_id,revision)
);
create index members_user_active on public.workspace_members(user_id,active);
create index tickets_workspace_updated on public.tickets(workspace_id,updated_at desc,id desc);

alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;
alter table public.tickets enable row level security;
alter table public.ticket_revisions enable row level security;

revoke all on public.workspaces,public.workspace_members,public.tickets,public.ticket_revisions from anon,authenticated;
grant select on public.workspaces,public.workspace_members,public.tickets,public.ticket_revisions to authenticated;
grant all on public.workspaces,public.workspace_members,public.tickets,public.ticket_revisions to service_role;

create policy member_self on public.workspace_members for select to authenticated
  using (user_id=(select auth.uid()) and active);
create policy workspace_read on public.workspaces for select to authenticated
  using (exists(select 1 from public.workspace_members m where m.workspace_id=id and m.user_id=(select auth.uid()) and m.active));
create policy ticket_read on public.tickets for select to authenticated
  using (exists(select 1 from public.workspace_members m where m.workspace_id=tickets.workspace_id and m.user_id=(select auth.uid()) and m.active));
create policy revision_read on public.ticket_revisions for select to authenticated
  using (exists(select 1 from public.tickets t where t.id=ticket_id));

-- Only the authenticated backend can invoke this RPC. p_user is taken from its verified JWT.
-- Membership and role are rechecked inside the same transaction as every mutation.
create function public.bugbrief_ticket_action(p_user uuid,p_workspace uuid,p_action text,p_data jsonb)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare
  member_role text;
  current_ticket public.tickets;
  found_ticket public.tickets;
  item_id uuid;
  expected integer;
  summaries jsonb;
  row_count integer;
begin
  select role into member_role from public.workspace_members
    where workspace_id=p_workspace and user_id=p_user and active for share;
  if member_role is null then raise exception 'Access denied' using errcode='42501'; end if;

  if p_action='list' then
    select coalesce(jsonb_agg(summary order by updated_at desc,id desc),'[]'),count(*)
      into summaries,row_count from (
        select id,updated_at,jsonb_build_object('id',id,'revision',revision,'status',status,
          'updated_at',updated_at,'created_by',created_by,'title',payload->>'title',
          'product_area',payload->>'product_area') as summary
        from public.tickets where workspace_id=p_workspace
          and position(lower(coalesce(p_data->>'search','')) in lower(payload->>'title')) > 0
          and (coalesce(p_data->>'area','')='' or payload->>'product_area'=p_data->>'area')
          and (coalesce(p_data->>'status','')='' or status=p_data->>'status')
        order by updated_at desc,id desc limit 21 offset least(greatest(coalesce((p_data->>'page')::integer,0),0),10000)*20
      ) r;
    return jsonb_build_object('items',case when row_count>20 then summaries - 20 else summaries end,'has_more',row_count>20);
  end if;

  if p_action='create' then
    if member_role='viewer' then raise exception 'Read-only role' using errcode='42501'; end if;
    insert into public.tickets(workspace_id,created_by,operation_id,payload,source_report,generation_metadata)
      values(p_workspace,p_user,p_data->>'operation_id',p_data->'payload',p_data->>'source_report',p_data->'generation_metadata')
      on conflict(workspace_id,created_by,operation_id) do nothing returning * into found_ticket;
    if found_ticket.id is null then
      select * into found_ticket from public.tickets where workspace_id=p_workspace and created_by=p_user and operation_id=p_data->>'operation_id';
      if found_ticket.payload <> p_data->'payload' or found_ticket.source_report is distinct from p_data->>'source_report' then
        raise exception 'Operation conflict' using errcode='BB409';
      end if;
    else
      insert into public.ticket_revisions(ticket_id,revision,payload,edited_by) values(found_ticket.id,1,found_ticket.payload,p_user);
    end if;
    return to_jsonb(found_ticket);
  end if;

  item_id := (p_data->>'ticket_id')::uuid;
  select * into current_ticket from public.tickets where workspace_id=p_workspace and id=item_id for update;
  if current_ticket.id is null then raise exception 'Ticket unavailable' using errcode='P0002'; end if;
  if p_action='get' then return to_jsonb(current_ticket); end if;
  if member_role='viewer' then raise exception 'Read-only role' using errcode='42501'; end if;

  if p_action='delete' then
    if member_role <> 'owner' and current_ticket.created_by <> p_user then
      raise exception 'Creator or owner required' using errcode='42501';
    end if;
    delete from public.tickets where workspace_id=p_workspace and id=item_id;
    return null;
  end if;

  expected := (p_data->>'expected_revision')::integer;
  if expected is null or expected <> current_ticket.revision then raise exception 'Revision conflict' using errcode='BB409'; end if;
  if p_action='update' then
    update public.tickets set payload=p_data->'payload',revision=revision+1,status='draft',
      reviewed_revision=null,reviewed_by=null,reviewed_at=null,updated_at=now()
      where workspace_id=p_workspace and id=item_id returning * into found_ticket;
    insert into public.ticket_revisions(ticket_id,revision,payload,edited_by)
      values(found_ticket.id,found_ticket.revision,found_ticket.payload,p_user);
    delete from public.ticket_revisions where ticket_id=item_id and revision <= found_ticket.revision-10;
  elsif p_action='review' then
    update public.tickets set status='reviewed',reviewed_revision=revision,reviewed_by=p_user,reviewed_at=now()
      where workspace_id=p_workspace and id=item_id returning * into found_ticket;
  else
    raise exception 'Unsupported operation' using errcode='22023';
  end if;
  return to_jsonb(found_ticket);
end;
$$;
revoke all on function public.bugbrief_ticket_action(uuid,uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.bugbrief_ticket_action(uuid,uuid,text,jsonb) to service_role;

insert into public.workspaces(id,name) values('00000000-0000-4000-8000-000000000010','LedgerFlow');
commit;
