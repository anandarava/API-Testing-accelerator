// In-memory mock of specs/petstore.yaml so the suite runs without a real backend.
// Start with `npm run mock`; Playwright starts it automatically when API_BASE_URL is empty.
import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';

const PORT = Number(process.env.MOCK_PORT ?? 4010);
const TOKEN = process.env.MOCK_TOKEN ?? 'local-dev-token';
const STATUSES = ['available', 'pending', 'sold'];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const pets = new Map();
const orders = new Map();

const send = (res, status, body) => {
  res.writeHead(status, body === undefined ? {} : { 'Content-Type': 'application/json' });
  res.end(body === undefined ? undefined : JSON.stringify(body));
};
const error = (res, status, code, message) => send(res, status, { code, message });
const isObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);

function nameProblem(name, required) {
  if (name === undefined) return required ? 'name is required' : null;
  if (typeof name !== 'string') return 'name must be a string';
  if (name.length < 1 || name.length > 50) return 'name must be 1-50 characters';
  if (!name.trim()) return 'name must not be blank';
  return null;
}

function nameTaken(name, exceptId) {
  return [...pets.values()].some((pet) => pet.name === name && pet.id !== exceptId);
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString('utf8');
  if (!(req.headers['content-type'] ?? '').includes('application/json')) return { problem: 'Content-Type must be application/json' };
  if (!raw) return { problem: 'Request body is required' };
  try {
    return { body: JSON.parse(raw) };
  } catch {
    return { problem: 'Body is not valid JSON' };
  }
}

function authenticate(req, res) {
  const header = req.headers.authorization ?? '';
  if (!header.startsWith('Bearer ')) return error(res, 401, 'unauthorized', 'Missing bearer token'), false;
  const token = header.slice(7);
  if (token === 'expired-token') return error(res, 401, 'token_expired', 'Token has expired'), false;
  if (token !== TOKEN) return error(res, 401, 'unauthorized', 'Invalid token'), false;
  return true;
}

const routes = {
  'GET /pets': (req, res, url) => {
    const limit = url.searchParams.has('limit') ? Number(url.searchParams.get('limit')) : 20;
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) return error(res, 400, 'invalid_limit', 'limit must be an integer 1-100');
    const status = url.searchParams.get('status');
    if (status !== null && !STATUSES.includes(status)) return error(res, 400, 'invalid_status', `status must be one of ${STATUSES.join(', ')}`);
    const list = [...pets.values()].filter((pet) => !status || pet.status === status).slice(0, limit);
    return send(res, 200, list);
  },
  'POST /pets': async (req, res) => {
    const { body, problem } = await readJson(req);
    if (problem) return error(res, 400, 'invalid_request', problem);
    if (!isObject(body)) return error(res, 400, 'invalid_request', 'Body must be a JSON object');
    const issue = nameProblem(body.name, true) ??
      (body.tag !== undefined && (typeof body.tag !== 'string' || body.tag.length > 20) ? 'tag must be a string of at most 20 characters' : null);
    if (issue) return error(res, 400, 'invalid_request', issue);
    if (nameTaken(body.name)) return error(res, 409, 'conflict', 'A pet with this name already exists');
    // id and status are read-only: anything the client sends is ignored.
    const pet = { id: randomUUID(), name: body.name, ...(body.tag !== undefined ? { tag: body.tag } : {}), status: 'available' };
    pets.set(pet.id, pet);
    return send(res, 201, pet);
  },
  'GET /pets/:id': (req, res, url, id) => (pets.has(id) ? send(res, 200, pets.get(id)) : error(res, 404, 'not_found', 'Pet not found')),
  'PATCH /pets/:id': async (req, res, url, id) => {
    const { body, problem } = await readJson(req);
    if (problem) return error(res, 400, 'invalid_request', problem);
    if (!pets.has(id)) return error(res, 404, 'not_found', 'Pet not found');
    if (!isObject(body)) return error(res, 400, 'invalid_request', 'Body must be a JSON object');
    const issue = nameProblem(body.name, false) ??
      (body.status !== undefined && !STATUSES.includes(body.status) ? `status must be one of ${STATUSES.join(', ')}` : null);
    if (issue) return error(res, 400, 'invalid_request', issue);
    if (body.name !== undefined && nameTaken(body.name, id)) return error(res, 400, 'conflict', 'A pet with this name already exists');
    const pet = { ...pets.get(id), ...(body.name !== undefined ? { name: body.name } : {}), ...(body.status !== undefined ? { status: body.status } : {}) };
    pets.set(id, pet);
    return send(res, 200, pet);
  },
  'DELETE /pets/:id': (req, res, url, id) => (pets.delete(id) ? send(res, 204) : error(res, 404, 'not_found', 'Pet not found')),
  'POST /orders': async (req, res) => {
    const { body, problem } = await readJson(req);
    if (problem) return error(res, 400, 'invalid_request', problem);
    if (!isObject(body)) return error(res, 400, 'invalid_request', 'Body must be a JSON object');
    if (typeof body.petId !== 'string' || !UUID.test(body.petId)) return error(res, 400, 'invalid_request', 'petId must be a UUID');
    if (!Number.isInteger(body.quantity) || body.quantity < 1 || body.quantity > 5) return error(res, 400, 'invalid_request', 'quantity must be an integer 1-5');
    const pet = pets.get(body.petId);
    if (!pet) return error(res, 400, 'unknown_pet', 'Pet does not exist');
    if (pet.status !== 'available') return error(res, 409, 'not_available', 'Pet is not available');
    pets.set(pet.id, { ...pet, status: 'pending' });
    const order = { id: randomUUID(), petId: pet.id, quantity: body.quantity, status: 'placed' };
    orders.set(order.id, order);
    return send(res, 201, order);
  },
  'GET /orders/:id': (req, res, url, id) => (orders.has(id) ? send(res, 200, orders.get(id)) : error(res, 404, 'not_found', 'Order not found')),
};

createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname === '/health') return send(res, 200, { status: 'ok' });
  const parts = url.pathname.split('/').filter(Boolean);
  const id = parts.length === 2 ? decodeURIComponent(parts[1]) : undefined;
  const key = `${req.method} /${parts[0] ?? ''}${id !== undefined ? '/:id' : ''}`;
  const handler = routes[key];
  if (!handler || parts.length > 2) return error(res, 404, 'not_found', 'Route not found');
  if (!authenticate(req, res)) return undefined;
  try {
    return await handler(req, res, url, id);
  } catch (exc) {
    return error(res, 500, 'server_error', String(exc));
  }
}).listen(PORT, '127.0.0.1', () => console.log(`Petstore mock listening on http://127.0.0.1:${PORT}`));
