import { test, expect } from '../../../src/fixtures';
import { expectError, expectJson } from '../../../src/helpers/assertions';
import { newOrder, unknownId } from '../../../src/data/builders';
import type { Order, Pet } from '../../../src/types/petstore';

test.describe('POST /orders', () => {
  test('orders an available pet and reserves it @smoke', async ({ orders, pets, createPet }) => {
    const pet = await createPet();
    const order = expectJson<Order>(await orders.place(newOrder(pet.id, { quantity: 2 })), 201, 'placeOrder');
    expect(order).toMatchObject({ petId: pet.id, quantity: 2, status: 'placed' });
    expect(expectJson<Pet>(await pets.getById(pet.id), 200).status).toBe('pending');
  });

  for (const quantity of [1, 5]) {
    test(`accepts quantity ${quantity}`, async ({ orders, createPet }) => {
      const pet = await createPet();
      expect(expectJson<Order>(await orders.place(newOrder(pet.id, { quantity })), 201).quantity).toBe(quantity);
    });
  }

  for (const quantity of [0, 6, 1.5]) {
    test(`rejects quantity ${quantity}`, async ({ orders, createPet }) => {
      const pet = await createPet();
      expectError(await orders.place(newOrder(pet.id, { quantity })), 400);
    });
  }

  test('rejects a petId that is not a UUID', async ({ orders }) => {
    expectError(await orders.place({ petId: 'not-a-uuid', quantity: 1 }), 400);
  });

  test('rejects ordering a pet that is not available', async ({ orders, pets, createPet }) => {
    const pet = await createPet();
    await pets.update(pet.id, { status: 'sold' });
    expect((await orders.place(newOrder(pet.id))).status).toBe(409);
  });
});

test.describe('GET /orders/{orderId}', () => {
  test('returns a placed order', async ({ orders, createPet }) => {
    const pet = await createPet();
    const placed = expectJson<Order>(await orders.place(newOrder(pet.id)), 201);
    expect(expectJson<Order>(await orders.getById(placed.id), 200, 'getOrder')).toEqual(placed);
  });

  test('returns 404 for an unknown order', async ({ orders }) => {
    expect((await orders.getById(unknownId())).status).toBe(404);
  });
});
