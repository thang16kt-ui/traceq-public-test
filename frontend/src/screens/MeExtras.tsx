// Phần mở rộng màn "Tôi" – được hoàn thiện ở hạng mục 10 (Web Push) và 13 (PWA/offline).
export function SyncPanel() {
  return <p className="muted">Chế độ làm việc offline chưa bật trong phiên bản này. Dữ liệu được gửi thẳng lên máy chủ.</p>;
}
export function InstallButton() {
  return <p className="muted">Cài ứng dụng lên màn hình chính sẽ có ở phiên bản sau.</p>;
}
export function PushToggle() {
  return null;
}
