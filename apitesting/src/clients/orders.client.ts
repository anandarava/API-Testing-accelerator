import { ApiClient, segment, type ApiResponse, type RequestOptions } from '../core/api-client';
import type { NewOrder } from '../types/petstore';

/** Client for the Store (orders) endpoints. */
export class OrdersClient extends ApiClient {
  place(order: NewOrder | Record<string, unknown>, options: RequestOptions = {}): Promise<ApiResponse> {
    return this.post('/orders', order, options);
  }

  getById(orderId: string, options?: RequestOptions): Promise<ApiResponse> {
    return this.get(`/orders/${segment(orderId)}`, options);
  }
}
