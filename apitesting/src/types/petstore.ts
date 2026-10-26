/** Types mirroring specs/petstore.yaml. */

export type PetStatus = 'available' | 'pending' | 'sold';
export type OrderStatus = 'placed' | 'approved' | 'delivered';

export interface NewPet {
  name: string;
  tag?: string;
}

export interface Pet extends NewPet {
  id: string;
  status: PetStatus;
}

export interface PetUpdate {
  name?: string;
  status?: PetStatus;
}

export interface NewOrder {
  petId: string;
  quantity: number;
}

export interface Order extends NewOrder {
  id: string;
  status: OrderStatus;
}

export interface ApiError {
  code: string;
  message: string;
}

export interface ListPetsQuery {
  limit?: number;
  status?: PetStatus;
}
