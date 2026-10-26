import { ApiClient, segment, type ApiResponse, type RequestOptions } from '../core/api-client';
import type { ListPetsQuery, NewPet, PetUpdate } from '../types/petstore';

/** Client for the Pets endpoints. Bodies are typed loosely (`unknown`) so negative tests can send invalid data. */
export class PetsClient extends ApiClient {
  list(query: ListPetsQuery | Record<string, string | number> = {}, options: RequestOptions = {}): Promise<ApiResponse> {
    return this.get('/pets', { ...options, params: { ...query } });
  }

  create(pet: NewPet | Record<string, unknown> | unknown, options: RequestOptions = {}): Promise<ApiResponse> {
    return this.post('/pets', pet, options);
  }

  getById(petId: string, options?: RequestOptions): Promise<ApiResponse> {
    return this.get(`/pets/${segment(petId)}`, options);
  }

  update(petId: string, changes: PetUpdate | Record<string, unknown>, options: RequestOptions = {}): Promise<ApiResponse> {
    return this.patch(`/pets/${segment(petId)}`, changes, options);
  }

  remove(petId: string, options?: RequestOptions): Promise<ApiResponse> {
    return this.delete(`/pets/${segment(petId)}`, options);
  }
}
