import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { PGlite } from '@electric-sql/pglite';

// Runs the real PostgreSQL migration with a minimal Supabase auth/role harness.
// This checks SQL and RLS behavior; it does not test the hosted PostgREST service.
const db = new PGlite();
const owner = '00000000-0000-4000-8000-000000000001';
const viewer = '00000000-0000-4000-8000-000000000002';
const contributor = '00000000-0000-4000-8000-000000000003';
const workspace = '00000000-0000-4000-8000-000000000010';
const other = '00000000-0000-4000-8000-000000000020';
try {
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth; create table auth.users(id uuid primary key);
    create function auth.uid() returns uuid language sql stable as $$
      select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
    grant usage on schema auth to authenticated; grant execute on function auth.uid() to authenticated;`);
  await db.exec(await readFile(new URL('../database/migrations/001_initial.sql', import.meta.url), 'utf8'));
  for (const id of [owner, viewer, contributor]) await db.query('insert into auth.users values($1)', [id]);
  await db.query('insert into workspaces(id,name) values($1,$2)', [other, 'Other workspace']);
  for (const [user, role] of [[owner,'owner'],[viewer,'viewer'],[contributor,'contributor']]) {
    await db.query('insert into workspace_members(workspace_id,user_id,role) values($1,$2,$3)',[workspace,user,role]);
  }
  await db.query('insert into workspace_members(workspace_id,user_id,role) values($1,$2,$3)',[other,owner,'owner']);
  const payload = JSON.parse(await readFile(new URL('../ml/data/examples.json',import.meta.url),'utf8'))[0].ticket;
  const rpc = async (user, ws, action, data) => (await db.query('select bugbrief_ticket_action($1,$2,$3,$4) result',[user,ws,action,JSON.stringify(data)])).rows[0].result;
  const expectCode = async (work, code) => {
    await assert.rejects(work, error => error.code === code);
  };
  const create = {payload,operation_id:'test-operation',source_report:null,generation_metadata:{provider:'test'}};
  const first = await rpc(owner,workspace,'create',create);
  assert.equal(first.source_report,null);
  assert.equal((await rpc(owner,workspace,'create',create)).id,first.id);
  await expectCode(()=>rpc(owner,workspace,'create',{...create,source_report:'changed'}),'BB409');
  await expectCode(()=>rpc(viewer,workspace,'create',{...create,operation_id:'viewer-operation'}),'42501');
  await expectCode(()=>rpc(owner,other,'get',{ticket_id:first.id}),'P0002');
  await rpc(contributor,workspace,'review',{ticket_id:first.id,expected_revision:1});
  const edited = await rpc(contributor,workspace,'update',{ticket_id:first.id,expected_revision:1,payload:{...payload,title:'Edited title'}});
  assert.equal(edited.revision,2); assert.equal(edited.status,'draft'); assert.equal(edited.reviewed_revision,null);
  await expectCode(()=>rpc(owner,workspace,'update',{ticket_id:first.id,expected_revision:1,payload}),'BB409');
  await expectCode(()=>rpc(contributor,workspace,'delete',{ticket_id:first.id}),'42501');
  for(let revision=2; revision<13; revision++) await rpc(owner,workspace,'update',{ticket_id:first.id,expected_revision:revision,payload});
  assert.equal((await db.query('select count(*)::integer n from ticket_revisions')).rows[0].n,10);

  await db.query("select set_config('request.jwt.claim.sub',$1,false)",[viewer]);
  await db.exec('set role authenticated');
  assert.equal((await db.query('select count(*)::integer n from tickets')).rows[0].n,1);
  await expectCode(()=>db.query('update tickets set payload=$1',[JSON.stringify(payload)]),'42501');
  await expectCode(()=>rpc(viewer,workspace,'get',{ticket_id:first.id}),'42501');
  await db.exec('reset role');
  await db.query('update workspace_members set active=false where user_id=$1',[viewer]);
  await expectCode(()=>rpc(viewer,workspace,'list',{}),'42501');
  await db.exec('set role authenticated');
  assert.equal((await db.query('select count(*)::integer n from tickets')).rows[0].n,0);
  await db.exec('reset role');
  await rpc(owner,workspace,'delete',{ticket_id:first.id});
  assert.equal((await db.query('select count(*)::integer n from ticket_revisions')).rows[0].n,0);
  console.log('PostgreSQL migration, RPC, role permissions, RLS, revision conflicts, and retention checks passed.');
} finally { await db.close(); }
