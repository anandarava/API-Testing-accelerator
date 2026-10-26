import type { NewOrder, NewPet } from '../types/petstore';

/** A value that is unique per call, for fields the API requires to be unique (e.g. pet names). */
export function uniqueName(prefix = 'qa'): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** A string of exactly `length` characters, for length boundary tests. */
export const ofLength = (length: number, char = 'x'): string => char.repeat(length);

/** A UUID that does not exist on the server, for 404 cases. */
export const unknownId = (): string => crypto.randomUUID();

export function newPet(overrides: Partial<NewPet> = {}): NewPet {
  return { name: uniqueName('pet'), tag: 'dog', ...overrides };
}

export function newOrder(petId: string, overrides: Partial<NewOrder> = {}): NewOrder {
  return { petId, quantity: 1, ...overrides };
}
