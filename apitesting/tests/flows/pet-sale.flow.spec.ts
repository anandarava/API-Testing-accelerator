import { test, expect } from '../../src/fixtures';
import { expectJson } from '../../src/helpers/assertions';
import { newPet } from '../../src/data/builders';
import type { Order, Pet } from '../../src/types/petstore';

/**
 * End-to-end flow: each step uses values captured by earlier steps. Every step is a test.step so
 * the report shows exactly where a journey breaks; created data is cleaned up even on failure.
 */
test.describe('Flow: selling a pet', () => {
  test('create → order → reserved → sold → cannot be ordered again @smoke', async ({ pets, orders, cleanup }) => {
    let pet!: Pet;
    let order!: Order;

    await test.step('S1 create a pet', async () => {
      pet = expectJson<Pet>(await pets.create(newPet({ tag: 'dog' })), 201, 'createPet');
      cleanup.add('delete pet', () => pets.remove(pet.id));
    });

    await test.step('S2 the new pet is available', async () => {
      expect(expectJson<Pet>(await pets.getById(pet.id), 200, 'getPet').status).toBe('available');
    });

    await test.step('S3 place an order for it', async () => {
      order = expectJson<Order>(await orders.place({ petId: pet.id, quantity: 1 }), 201, 'placeOrder');
      expect(order.status).toBe('placed');
    });

    await test.step('S4 the order is retrievable and unchanged', async () => {
      expect(expectJson<Order>(await orders.getById(order.id), 200, 'getOrder')).toEqual(order);
    });

    await test.step('S5 the pet is reserved (pending) and listed as pending', async () => {
      expect(expectJson<Pet>(await pets.getById(pet.id), 200).status).toBe('pending');
      const pending = expectJson<Pet[]>(await pets.list({ status: 'pending', limit: 100 }), 200, 'listPets');
      expect(pending.map((p) => p.id)).toContain(pet.id);
    });

    await test.step('S6 staff mark the pet as sold', async () => {
      expect(expectJson<Pet>(await pets.update(pet.id, { status: 'sold' }), 200, 'updatePet').status).toBe('sold');
    });

    await test.step('S7 a sold pet cannot be ordered again', async () => {
      expect((await orders.place({ petId: pet.id, quantity: 1 })).status).toBe(409);
    });
  });
});
