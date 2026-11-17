// Hàng đợi offline: gửi lại cùng UUID/khóa, giữ lại khi mất mạng, xóa sạch khi đăng xuất.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearOffline, enqueuePhoto, enqueueProposal, flushQueue, pendingCounts } from './offline';

const json = (status: number, body: any) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

afterEach(async () => { vi.restoreAllMocks(); await clearOffline(); });

describe('hàng đợi offline', () => {
  it('gửi đề xuất rồi gắn ảnh vào đúng mục lỗi theo loại lỗi', async () => {
    const calls: { url: string; key: string | null }[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: any, init: any) => {
      calls.push({ url: String(input), key: new Headers(init.headers).get('Idempotency-Key') });
      if (String(input).endsWith('/defect-cases')) return json(201, { id: 'case-1', items: [{ id: 'item-a', defect_type_id: 'type-a' }, { id: 'item-b', defect_type_id: 'type-b' }] });
      return json(201, { id: 'photo' });
    });
    await enqueueProposal({ id: 'p1', body: { id: 'p1' }, photos: [{ id: 'ph1', defectTypeId: 'type-b', blob: new Blob(['x']) }], createdAt: new Date().toISOString() });
    expect(await flushQueue()).toBe(0);
    expect(calls.map((c) => c.url)).toEqual(['/api/v1/defect-cases', '/api/v1/defect-cases/case-1/items/item-b/photos']);
    expect(calls[0].key).toBe('offline-p1');   // khóa cố định → gửi lại không tạo trùng
    expect(calls[1].key).toBe('ph1');
  });

  it('giữ mục khi mất mạng và gửi lại cùng khóa ở lần sau', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await enqueuePhoto({ id: 'ph2', caseId: 'c', itemId: 'i', kind: 'truoc', blob: new Blob(['y']) });
    expect(await flushQueue()).toBe(1);
    fetchMock.mockResolvedValueOnce(json(201, { id: 'ph2' }));
    expect(await flushQueue()).toBe(0);
    expect(new Headers((fetchMock.mock.calls[1][1] as any).headers).get('Idempotency-Key')).toBe('ph2');
  });

  it('xóa sạch dữ liệu chờ khi đăng xuất', async () => {
    await enqueuePhoto({ id: 'ph3', caseId: 'c', itemId: 'i', kind: 'truoc', blob: new Blob(['z']) });
    expect((await pendingCounts()).photos).toBe(1);
    await clearOffline();
    expect(await pendingCounts()).toEqual({ photos: 0, proposals: 0 });
  });
});
