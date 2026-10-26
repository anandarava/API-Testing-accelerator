import { test as base, expect, type APIRequestContext } from '@playwright/test';
import { env, requireToken } from '../config/env';
import { ApiClient, type Exchange } from '../core/api-client';
import { Cleanup } from '../core/cleanup';
import { PetsClient } from '../clients/pets.client';
import { OrdersClient } from '../clients/orders.client';
import type { Pet } from '../types/petstore';
import { newPet } from '../data/builders';
import { expectJson } from '../helpers/assertions';

type ClientFactory = <T extends ApiClient>(Client: new (request: APIRequestContext, log: Exchange[]) => T, token?: string | null) => Promise<T>;

export interface ApiFixtures {
  /** Every request made in the test; attached to the report when the test fails. */
  apiLog: Exchange[];
  /** Build a client with specific credentials: a token, or `null` for no credentials. */
  clientAs: ClientFactory;
  /** Authenticated clients (API_TOKEN). */
  pets: PetsClient;
  orders: OrdersClient;
  /** Register cleanup that runs after the test, even when it fails. */
  cleanup: Cleanup;
  /** Create a pet through the API and delete it after the test. */
  createPet: (overrides?: Partial<Pet>) => Promise<Pet>;
}

export const test = base.extend<ApiFixtures>({
  apiLog: async ({}, use, testInfo) => { // eslint-disable-line no-empty-pattern
    const log: Exchange[] = [];
    await use(log);
    if (testInfo.status !== testInfo.expectedStatus && log.length) {
      await testInfo.attach('api-exchanges.json', { body: JSON.stringify(log, null, 2), contentType: 'application/json' });
    }
  },

  clientAs: async ({ playwright, apiLog }, use) => {
    const contexts: APIRequestContext[] = [];
    const factory: ClientFactory = async (Client, token = requireToken()) => {
      const context = await playwright.request.newContext({
        baseURL: env.baseUrl,
        extraHTTPHeaders: { Accept: 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      contexts.push(context);
      return new Client(context, apiLog);
    };
    await use(factory);
    await Promise.all(contexts.map((context) => context.dispose()));
  },

  pets: async ({ clientAs }, use) => use(await clientAs(PetsClient)),
  orders: async ({ clientAs }, use) => use(await clientAs(OrdersClient)),

  cleanup: async ({}, use, testInfo) => { // eslint-disable-line no-empty-pattern
    const cleanup = new Cleanup();
    await use(cleanup);
    const failures = await cleanup.runAll();
    if (failures.length) {
      testInfo.annotations.push({ type: 'cleanup', description: failures.join('\n') });
      if (testInfo.status === testInfo.expectedStatus) throw new Error(`Cleanup failed:\n${failures.join('\n')}`);
    }
  },

  createPet: async ({ pets, cleanup }, use) => {
    await use(async (overrides = {}) => {
      const pet = expectJson<Pet>(await pets.create(newPet(overrides)), 201, 'createPet');
      cleanup.add(`delete pet ${pet.id}`, async () => {
        const response = await pets.remove(pet.id);
        if (![204, 404].includes(response.status)) throw new Error(`DELETE /pets/${pet.id} returned ${response.status}`);
      });
      return pet;
    });
  },
});

export { expect };
