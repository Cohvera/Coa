import Fastify from 'fastify';
import cors from '@fastify/cors';
import { pool } from './db.js';

const app = Fastify({ logger: true });
await app.register(cors, { origin: true });

function toNumber(value) {
  return value === null || value === undefined ? 0 : Number(value);
}

app.get('/api/health', async () => ({ ok: true, service: 'cohvera-pulse-api' }));

app.get('/api/companies', async () => {
  const { rows } = await pool.query('select id, name from companies order by name');
  return rows;
});

app.get('/api/dashboard/:companyId', async (request) => {
  const companyId = Number(request.params.companyId);
  const { rows } = await pool.query(
    `select c.id, c.name, k.snapshot_date, k.bank, k.receivables, k.payables, k.drafts, k.wip, k.gross_margin_pct
     from companies c
     left join lateral (
       select * from kpi_snapshots where company_id = c.id order by snapshot_date desc, id desc limit 1
     ) k on true
     where c.id = $1`,
    [companyId]
  );
  if (!rows[0]) return { error: 'Company not found' };
  const row = rows[0];
  const bank = toNumber(row.bank);
  const receivables = toNumber(row.receivables);
  const payables = toNumber(row.payables);
  const drafts = toNumber(row.drafts);
  const wip = toNumber(row.wip);
  return {
    company: { id: row.id, name: row.name },
    snapshotDate: row.snapshot_date,
    bank,
    receivables,
    payables,
    drafts,
    wip,
    grossMarginPct: toNumber(row.gross_margin_pct),
    availableCashPosition: bank + receivables + drafts + wip - payables,
  };
});

app.get('/api/kpi-snapshots/:companyId', async (request) => {
  const { rows } = await pool.query(
    'select * from kpi_snapshots where company_id = $1 order by snapshot_date desc, id desc limit 26',
    [Number(request.params.companyId)]
  );
  return rows;
});

app.post('/api/kpi-snapshots', async (request, reply) => {
  const b = request.body || {};
  const { rows } = await pool.query(
    `insert into kpi_snapshots(company_id, snapshot_date, bank, receivables, payables, drafts, wip, gross_margin_pct)
     values($1,$2,$3,$4,$5,$6,$7,$8) returning *`,
    [b.companyId, b.snapshotDate, b.bank, b.receivables, b.payables, b.drafts, b.wip || 0, b.grossMarginPct || 0]
  );
  reply.code(201);
  return rows[0];
});

app.get('/api/cashflow/:companyId', async (request) => {
  const companyId = Number(request.params.companyId);
  const dashboard = await app.inject({ method: 'GET', url: `/api/dashboard/${companyId}` });
  const base = JSON.parse(dashboard.body);
  const { rows } = await pool.query(
    'select week_no, income, expense from cashflow_forecasts where company_id = $1 order by week_no asc',
    [companyId]
  );
  let balance = toNumber(base.bank);
  return rows.map((row) => {
    const opening = balance;
    balance = balance + toNumber(row.income) - toNumber(row.expense);
    return { weekNo: row.week_no, opening, income: toNumber(row.income), expense: toNumber(row.expense), closing: balance };
  });
});

app.get('/api/projects/:companyId', async (request) => {
  const { rows } = await pool.query(
    `select id, name, revenue, cost, status,
            case when revenue > 0 then round(((revenue-cost)/revenue)*100, 2) else 0 end as margin_pct
     from projects where company_id = $1 order by id desc`,
    [Number(request.params.companyId)]
  );
  return rows;
});

const port = Number(process.env.PORT || 3001);
await app.listen({ port, host: '0.0.0.0' });
