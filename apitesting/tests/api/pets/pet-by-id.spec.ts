import { test, expect } from '../../../src/fixtures';
import { expectError, expectJson } from '../../../src/helpers/assertions';
import { unknownId } from '../../../src/data/builders';
import type { Pet } from '../../../src/types/petstore';

test.describe('GET /pets/{petId}', () => {
  test('returns an existing pet @smoke', async ({ pets, createPet }) => {
    const created = await createPet({ tag: 'parrot' });
    const pet = expectJson<Pet>(await pets.getById(created.id), 200, 'getPet');
    expect(pet).toEqual(created);
  });

  test('returns 404 for an unknown pet', async ({ pets }) => {
    expect((await pets.getById(unknownId())).status).toBe(404);
  });
});

test.describe('PATCH /pets/{petId}', () => {
  test('updates the name and status', async ({ pets, createPet }) => {
    const created = await createPet();
    const changes = { name: `${created.name}-renamed`, status: 'sold' as const };
    const updated = expectJson<Pet>(await pets.update(created.id, changes), 200, 'updatePet');
    expect(updated).toMatchObject({ id: created.id, ...changes });
    expect(expectJson<Pet>(await pets.getById(created.id), 200)).toMatchObject(changes);
  });

  test('rejects a status outside the allowed values', async ({ pets, createPet }) => {
    const created = await createPet();
    expectError(await pets.update(created.id, { status: 'lost' }), 400);
    expect(expectJson<Pet>(await pets.getById(created.id), 200).status).toBe('available');
  });

  test('returns 404 for an unknown pet', async ({ pets }) => {
    expect((await pets.update(unknownId(), { status: 'sold' })).status).toBe(404);
  });
});

test.describe('DELETE /pets/{petId}', () => {
  test('deletes a pet so it can no longer be read', async ({ pets, createPet }) => {
    const created = await createPet();
    expect((await pets.remove(created.id)).status).toBe(204);
    expect((await pets.getById(created.id)).status).toBe(404);
  });

  test('returns 404 for an unknown pet', async ({ pets }) => {
    expect((await pets.remove(unknownId())).status).toBe(404);
  });
});
