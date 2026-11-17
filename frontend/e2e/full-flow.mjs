// E2E giao diện thật, nhiều vai trò (một cấp duyệt): tạo lỗi ưu tiên → gửi → chụp → Quản lý xác nhận + chốt phương án → Giám sát hoàn tất → Quản lý đóng → xuất PDF.
// Chạy với máy chủ có dữ liệu mẫu (ENVIRONMENT=demo):  node e2e/full-flow.mjs http://localhost:8080 <mật-khẩu-demo> <ảnh.jpg>
import { createRequire } from 'node:module';
// playwright: cài bằng `npm i -D playwright` hoặc dùng bản cài sẵn (NODE_PATH).
const { chromium, devices } = createRequire(import.meta.url)('playwright');

const [base = 'http://localhost:8080', password, photo] = process.argv.slice(2);
if (!password || !photo) { console.error('Cần: URL, mật khẩu demo, đường dẫn ảnh JPG'); process.exit(2); }
const browser = await chromium.launch();
const errors = [];

async function as(user, mobile = true) {
  const ctx = await browser.newContext(mobile ? { ...devices['Pixel 7'] } : { viewport: { width: 1366, height: 900 } });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(`${user}: ${e.message}`));
  await page.goto(base + '/');
  await page.getByLabel('Tên đăng nhập hoặc mã nhân viên').fill(user);
  await page.locator('input[type=password]').fill(password);
  await page.getByRole('button', { name: 'Đăng nhập' }).click();
  await page.waitForSelector('.content');
  return page;
}
const step = (name) => console.log('✓ ' + name);
const serial = 'E2E-' + Date.now();

// 1. Người tạo: tạo đề xuất (lỗi ưu tiên → Quản lý duyệt), tờ tổng quan, gửi, chụp minh chứng.
const creator = await as('demo.nguoitao');
await creator.goto(base + '/#/tao');
await creator.getByLabel('Serial sản phẩm').fill(serial);
await creator.getByLabel('Serial sản phẩm').blur();
await creator.getByLabel('Đợt kiểm tra').selectOption({ index: 1 });
await creator.getByLabel('Loại lỗi').selectOption({ label: 'Nứt bề mặt (ƯU TIÊN)' });
await creator.getByText('Lỗi ưu tiên', { exact: true }).waitFor();
await creator.getByText('Trung bình', { exact: true }).click();
await creator.getByRole('button', { name: 'Xem tờ tổng quan' }).click();
await creator.getByText('TỜ TỔNG QUAN ĐỀ XUẤT SẢN PHẨM LỖI').waitFor();
const code = (await creator.locator('.a4-code').innerText()).trim();
step(`Tạo nháp ${code} và xem tờ tổng quan`);
await creator.getByRole('button', { name: 'Gửi đề xuất' }).click();
await creator.getByRole('button', { name: 'Tải QR' }).waitFor();
step('Gửi đề xuất, hiện QR');
await creator.getByRole('button', { name: 'Chụp minh chứng ngay' }).click();
await creator.locator('input[type=file]').first().setInputFiles(photo);
await creator.getByText('Đã có 1 ảnh').waitFor();
await creator.getByRole('button', { name: 'Gửi minh chứng' }).click();
await creator.getByText('Chờ xác nhận').first().waitFor();
const url = creator.url();
step('Chụp và gửi minh chứng');

// 2. Quản lý (một cấp duyệt – lỗi ưu tiên): xác nhận lỗi, chốt phương án Sửa → Đang xử lý.
const manager = await as('demo.quanly', false);
await manager.goto(url);
await manager.getByText('Hệ thống đã kiểm tra trước').waitFor();
await manager.getByRole('button', { name: 'Xác nhận lỗi' }).click();
await manager.getByText('Đề xuất đã được xác nhận bởi').waitFor();
step('Quản lý xác nhận lỗi ưu tiên');
await manager.getByText(/^Sửa/).first().click();
await manager.getByText('Một cấp duyệt: chốt xong chuyển thẳng sang xử lý.').waitFor();
await manager.getByRole('button', { name: 'Chốt phương án' }).click();
await manager.getByText('Đang xử lý').first().waitFor();
step('Quản lý chốt phương án → Đang xử lý (không còn bước cấp trên)');

// 3. Giám sát: ảnh sau xử lý, chi phí thực tế, hoàn tất.
const supervisor = await as('demo.giamsat');
await supervisor.goto(url);
await supervisor.getByText('Hoàn tất xử lý', { exact: true }).first().waitFor();
await supervisor.locator('.after-row input[type=file]').first().setInputFiles(photo);
await supervisor.waitForTimeout(1500);
await supervisor.getByLabel('Vật tư (VND)').fill('120000');
await supervisor.getByLabel('Số giờ công').fill('1.5');
await supervisor.getByRole('button', { name: 'Máy móc' }).click();
await supervisor.getByRole('button', { name: 'Hoàn tất xử lý' }).click();
await supervisor.getByText('Kiểm tra và đóng').waitFor();
step('Giám sát hoàn tất xử lý (chi phí thực tế + nguyên nhân gốc + ảnh sau)');

// 4. Quản lý: kiểm tra và đóng.
await manager.reload();
await manager.getByRole('button', { name: 'Đóng đề xuất' }).click();
await manager.getByText('Đã đóng').first().waitFor();
step('Quản lý đóng đề xuất');

// 5. Quản lý: xuất PDF.
await manager.goto(url);
const [pdf] = await Promise.all([manager.waitForEvent('download'), manager.getByRole('button', { name: 'Xuất PDF' }).click()]);
const file = await pdf.path();
const { readFileSync } = await import('node:fs');
if (!readFileSync(file).subarray(0, 4).toString().startsWith('%PDF')) throw new Error('PDF không hợp lệ');
step(`Xuất PDF ${pdf.suggestedFilename()}`);

await browser.close();
if (errors.length) { console.error('Lỗi JS trên trang:', errors); process.exit(1); }
console.log(`E2E giao diện ĐẠT cho ${code}`);
