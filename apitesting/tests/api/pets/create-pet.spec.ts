import { test, expect } from '../../../src/fixtures';
import { PetsClient } from '../../../src/clients/pets.client';
import { expectError, expectJson } from '../../../src/helpers/assertions';
import { newPet, ofLength } from '../../../src/data/builders';
import { env } from '../../../src/config/env';
import type { Pet } from '../../../src/types/petstore';

test.describe('POST /pets', () => {
  test('creates a pet with only the required name @smoke', async ({ pets, cleanup }) => {
    const body = { name: newPet().name };
    const pet = expectJson<Pet>(await pets.create(body), 201, 'createPet');
    cleanup.add('delete pet', () => pets.remove(pet.id));

    expect(pet.name).toBe(body.name);
    expect(pet.status).toBe('available');
    expect(pet.tag).toBeUndefined();
  });

  test('creates a pet with name and optional tag', async ({ pets, cleanup }) => {
    const body = newPet({ tag: 'cat' });
    const pet = expectJson<Pet>(await pets.create(body), 201, 'createPet');
    cleanup.add('delete pet', () => pets.remove(pet.id));

    expect(pet).toMatchObject({ name: body.name, tag: body.tag });
  });

  for (const length of [1, 50]) {
    test(`accepts a name of exactly ${length} character(s)`, async ({ pets, cleanup }) => {
      // Fixed names collide across runs; make them unique while keeping the exact length.
      const name = `${Date.now()}`.slice(-Math.min(length, 13)).padStart(length, 'x');
      const pet = expectJson<Pet>(await pets.create({ name }), 201, 'createPet');
      cleanup.add('delete pet', () => pets.remove(pet.id));
      expect(pet.name).toHaveLength(length);
    });
  }

  const invalidBodies: [string, unknown][] = [
    ['name is missing', { tag: 'dog' }],
    ['name is null', { name: null }],
    ['name is a number', { name: 123 }],
    ['name is empty', { name: '' }],
    ['name has 51 characters', { name: ofLength(51) }],
    ['tag has 21 characters', { name: newPet().name, tag: ofLength(21) }],
    ['body is an array', [{ name: 'Rex' }]],
  ];
  for (const [condition, body] of invalidBodies) {
    test(`rejects the request when ${condition}`, async ({ pets }) => {
      expectError(await pets.create(body), 400);
    });
  }

  test('rejects malformed JSON', async ({ pets }) => {
    expectError(await pets.create(undefined, { raw: '{"name": "Rex"' }), 400);
  });

  test('rejects a duplicate pet name with 409', async ({ pets, createPet }) => {
    const existing = await createPet();
    const response = await pets.create({ name: existing.name });
    expect(response.status, response.text).toBe(409);
  });

  test('ignores read-only id and status sent by the client', async ({ pets, cleanup }) => {
    const sentId = crypto.randomUUID();
    const pet = expectJson<Pet>(await pets.create({ ...newPet(), id: sentId, status: 'sold' }), 201, 'createPet');
    cleanup.add('delete pet', () => pets.remove(pet.id));
    expect(pet.id).not.toBe(sentId);
    expect(pet.status).toBe('available');
  });

  test.describe('authentication', () => {
    test('rejects a request without credentials @smoke', async ({ clientAs }) => {
      const anonymous = await clientAs(PetsClient, null);
      expectError(await anonymous.create(newPet()), 401);
    });

    test('rejects an invalid token', async ({ clientAs }) => {
      const intruder = await clientAs(PetsClient, 'invalid-token');
      expectError(await intruder.create(newPet()), 401);
    });

    test('rejects an expired token', async ({ clientAs }) => {
      test.skip(!env.expiredToken, 'Set API_TOKEN_EXPIRED to run this case');
      const expired = await clientAs(PetsClient, env.expiredToken);
      expectError(await expired.create(newPet()), 401);
    });
  });
});
