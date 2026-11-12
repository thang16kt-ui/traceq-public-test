// Nén ảnh phía client trước khi gửi: tối đa 1600px, JPEG ~80%. Server vẫn kiểm tra lại.
const MAX_SIDE = 1600;

export async function compressImage(file: Blob): Promise<Blob> {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' } as ImageBitmapOptions);
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.8));
    return blob && blob.size < file.size ? blob : file;
  } catch {
    return file; // trình duyệt cũ: gửi nguyên ảnh, server sẽ thu nhỏ
  }
}
