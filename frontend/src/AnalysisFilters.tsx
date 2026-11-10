import type {Row} from './api';

export default function AnalysisFilters({products,batches,productId,batchId,onProduct,onBatch,disabled=false}:{products:Row[];batches:Row[];productId:string;batchId:string;onProduct:(id:string)=>void;onBatch:(id:string)=>void;disabled?:boolean}){
  const children=batches.filter(batch=>batch.product_type_id===productId);
  return <section className="analysis-product-filters" aria-label="Lọc phân tích theo sản phẩm và lô">
    <label><span>Loại sản phẩm</span><select aria-label="Loại sản phẩm phân tích" value={productId} disabled={disabled} onChange={event=>onProduct(event.target.value)}>
      <option value="">Tất cả loại sản phẩm</option>{products.map(product=><option key={product.id} value={product.id}>{product.sku} · {product.name}{product.is_active===false?' (ngừng sử dụng)':''}</option>)}
    </select></label>
    <label><span>Lô sản phẩm</span><select aria-label="Lô sản phẩm phân tích" value={batchId} disabled={disabled||!productId} onChange={event=>onBatch(event.target.value)}>
      <option value="">{!productId?'Chọn loại sản phẩm trước':children.length?'Tất cả lô của loại sản phẩm':'Chưa có lô thuộc loại sản phẩm này'}</option>{children.map(batch=><option key={batch.id} value={batch.id}>{batch.lot_code}{batch.effective_active===false?' (ngừng sử dụng)':''}</option>)}
    </select></label>
    <button type="button" className="btn" disabled={disabled||!productId} onClick={()=>onProduct('')}>Bỏ lọc sản phẩm / lô</button>
    <p>{disabled?'Bộ lọc sản phẩm dùng khi kết nối dữ liệu hệ thống.':'Số liệu, biểu đồ, so sánh và chi phí được tính theo thời gian, loại sản phẩm và lô đã chọn.'}</p>
  </section>;
}
