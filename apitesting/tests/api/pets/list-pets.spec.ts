import { test, expect } from '../../../src/fixtures';
import { expectError, expectJson } from '../../../src/helpers/assertions';
import type { Pet } from '../../../src/types/petstore';

test.describe('GET /pets', () => {
  test('lists pets matching the documented schema @smoke', async ({ pets, createPet }) => {
    const created = await createPet();
    const list = expectJson<Pet[]>(await pets.list({ limit: 100 }), 200, 'listPets');
    expect(list.map((pet) => pet.id)).toContain(created.id);
  });

  test('filters by status', async ({ pets, createPet }) => {
    const sold = await createPet();
    await pets.update(sold.id, { status: 'sold' });
    const list = expectJson<Pet[]>(await pets.list({ status: 'sold', limit: 100 }), 200, 'listPets');
    expect(list.every((pet) => pet.status === 'sold')).toBe(true);
    expect(list.map((pet) => pet.id)).toContain(sold.id);
  });

  for (const limit of [1, 100]) {
    test(`accepts limit=${limit} and returns at most that many pets`, async ({ pets, createPet }) => {
      await createPet();
      const list = expectJson<Pet[]>(await pets.list({ limit }), 200, 'listPets');
      expect(list.length).toBeGreaterThan(0);
      expect(list.length).toBeLessThanOrEqual(limit);
    });
  }

  for (const limit of [0, 101, 'ten']) {
    test(`rejects limit=${limit}`, async ({ pets }) => {
      expectError(await pets.list({ limit }), 400);
    });
  }

  test('rejects an unknown status filter', async ({ pets }) => {
    expectError(await pets.list({ status: 'lost' }), 400);
  });
});
