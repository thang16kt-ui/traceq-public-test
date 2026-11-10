import {useEffect, useRef, useState} from 'react';
import type {FormEvent, KeyboardEvent, ReactNode} from 'react';
import {api, allCatalogRows, makeRequestId, errorMessage, formatTime} from './api';
import type {Row} from './api';

const kinds = [['product-types','Loại sản phẩm'],['batches','Lô sản xuất'],['defect-types','Loại lỗi']];
const severities:Row = {low:'Nhẹ', medium:'Trung bình', high:'Nặng', critical:'Nghiêm trọng'};
const actions:Row = {create:'Thêm', update:'Sửa', deactivate:'Ngừng sử dụng', restore:'Khôi phục', delete:'Xóa hẳn'};
const fields:Row = {name:'Tên',sku:'Mã SKU',code:'Mã lỗi',lot_code:'Mã lô',unit_of_measure:'Đơn vị tính',severity_default:'Mức độ',is_active:'Đang sử dụng',product_type_id:'Loại sản phẩm'};
function Field({label,children}:{label:string;children:ReactNode}){
  return <label className="field"><span>{label}</span>{children}</label>;
}

export default function CatalogSetup({demo,demoLogin,user,onAuthenticated,onSaved,onSuccess}:{demo:boolean;demoLogin:boolean;user:Row;onAuthenticated:(data:Row)=>void;onSaved:()=>void;onSuccess:(message:string)=>void}){
  const [tab,setTab]=useState('product-types'),[state,setState]=useState('active'),[page,setPage]=useState(1);
  const [entries,setEntries]=useState<Row[]>([]),[total,setTotal]=useState(0),[products,setProducts]=useState<Row[]>([]);
  const [loading,setLoading]=useState(true),[error,setError]=useState(''),[revision,setRevision]=useState(0),[busy,setBusy]=useState(false);
  const [editing,setEditing]=useState<Row|null>(null),[confirmation,setConfirmation]=useState<{item:Row;restore:boolean}|null>(null),[reason,setReason]=useState('');
  const [history,setHistory]=useState<Row|null>(null),[historyPage,setHistoryPage]=useState(1),[historyData,setHistoryData]=useState<Row>({items:[],total:0}),[historyLoading,setHistoryLoading]=useState(false),[historyError,setHistoryError]=useState(''),[historyRevision,setHistoryRevision]=useState(0);
  const [showLogin,setShowLogin]=useState(false),[loginError,setLoginError]=useState('');
  const keys=useRef(new Map<string,string>());
  const canManage=!demo && user.username!=='public.guest' && ['admin','manager'].includes(user.role);
  const tabLabel=kinds.find(([kind])=>kind===tab)![1];

  function dialogKeys(event:KeyboardEvent<HTMLElement>,close:()=>void){
    if(event.key==='Escape'&&!busy){event.preventDefault();close();}
    if(event.key!=='Tab')return;
    const controls=[...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled)')].filter(element=>element.offsetParent!==null);
    const first=controls[0],last=controls[controls.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
  function historyValue(field:string,value:any){
    if(value==null)return '—';
    if(typeof value==='boolean')return value?'Có':'Không';
    if(field==='severity_default')return severities[value]||value;
    if(field==='product_type_id')return products.find(product=>product.id===value)?.name||value;
    return String(value);
  }

  useEffect(()=>{
    let cancelled=false;
    setLoading(true);setError('');setEntries([]);
    if(demo){setLoading(false);return;}
    Promise.all([api(`/${tab}?state=${state}&page=${page}&page_size=20`),allCatalogRows('/product-types?state=all')])
      .then(([data,parents])=>{if(cancelled)return;setEntries(data.items);setTotal(data.total);setProducts(parents);if(!data.items.length&&page>1)setPage(page-1);})
      .catch(e=>{if(!cancelled)setError(errorMessage(e));})
      .finally(()=>{if(!cancelled)setLoading(false);});
    return()=>{cancelled=true;};
  },[tab,state,page,revision,demo,user.id]);

  useEffect(()=>{
    if(!history)return;
    let cancelled=false;setHistoryLoading(true);setHistoryError('');
    api(`/${tab}/${history.id}/history?page=${historyPage}&page_size=20`)
      .then(data=>{if(!cancelled)setHistoryData(data);})
      .catch(e=>{if(!cancelled)setHistoryError(errorMessage(e));})
      .finally(()=>{if(!cancelled)setHistoryLoading(false);});
    return()=>{cancelled=true;};
  },[history,historyPage,historyRevision,tab]);

  function requestKey(path:string, body:Row){
    const signature=JSON.stringify([path,body]);
    if(!keys.current.has(signature))keys.current.set(signature,makeRequestId());
    return keys.current.get(signature)!;
  }
  function reload(){setRevision(value=>value+1);onSaved();}
  function changeTab(value:string){setTab(value);setPage(1);setEditing(null);setConfirmation(null);setHistory(null);setError('');}
  function newEntry(){setError('');setEditing(tab==='product-types'?{sku:'',name:'',unit_of_measure:'cái'}:tab==='batches'?{product_type_id:'',lot_code:''}:{code:'',name:'',severity_default:'medium'});}

  async function save(event:FormEvent){
    event.preventDefault();if(!editing||!canManage)return;
    setBusy(true);setError('');
    const body:Row=tab==='product-types'?{sku:editing.sku,name:editing.name,unit_of_measure:editing.unit_of_measure}:tab==='batches'?{product_type_id:editing.product_type_id,lot_code:editing.lot_code}:{code:editing.code,name:editing.name,severity_default:editing.severity_default};
    if(editing.id)Object.assign(body,{row_version:editing.row_version,reason:editing.reason});
    const path=`/${tab}${editing.id?`/${editing.id}`:''}`;
    try{
      await api(path,{method:editing.id?'PATCH':'POST',body:JSON.stringify(body)},requestKey(path,body));
      keys.current.clear();setEditing(null);onSuccess('Đã lưu danh mục.');reload();
    }catch(e){setError(errorMessage(e));}finally{setBusy(false);}
  }

  async function confirm(event:FormEvent){
    event.preventDefault();if(!confirmation||!canManage)return;
    setBusy(true);setError('');
    const {item,restore}=confirmation;
    const body={row_version:item.row_version,reason};
    const path=`/${tab}/${item.id}${restore?'/restore':''}`;
    try{
      const data=await api(path,{method:restore?'POST':'DELETE',body:JSON.stringify(body)},requestKey(path,body));
      keys.current.clear();setConfirmation(null);
      onSuccess(data.operation==='delete'?'Đã xóa danh mục chưa được sử dụng.':data.operation==='restore'?'Đã khôi phục danh mục.':'Đã ngừng sử dụng. Hồ sơ và báo cáo cũ được giữ nguyên.');reload();
    }catch(e){setError(errorMessage(e));}finally{setBusy(false);}
  }

  async function login(event:FormEvent<HTMLFormElement>){
    event.preventDefault();setBusy(true);setLoginError('');
    const values=Object.fromEntries(new FormData(event.currentTarget));
    try{
      const data=await api('/auth/catalog-login',{method:'POST',body:JSON.stringify(values)});
      setShowLogin(false);onAuthenticated(data);onSuccess('Đã xác thực quyền quản lý danh mục.');
    }catch(e){setLoginError(errorMessage(e));}finally{setBusy(false);}
  }

  const errorBox=error&&<div className="catalog-error" role="alert">{error}<button type="button" className="btn" disabled={busy} onClick={()=>{setError('');setEditing(null);setConfirmation(null);reload();}}>Tải lại danh sách</button></div>;
  return <section className="panel catalog-admin" aria-labelledby="catalog-title">
    <div className="panel-heading"><div><h2 id="catalog-title">Danh mục vận hành</h2><p>Quản lý sản phẩm, lô và loại lỗi. Danh mục đã dùng được giữ trong lịch sử.</p></div></div>
    {!canManage&&<div className="catalog-access"><p>{demo?'Bản minh họa chỉ đọc.':demoLogin?'Bản test public: nhập mật khẩu bất kỳ để quản lý danh mục.':'Ghi nhận thông thường không cần đăng nhập. Thay đổi danh mục cần tài khoản quản lý hoặc admin.'}</p><button className="btn" disabled={demo||busy} onClick={()=>setShowLogin(true)}>Đăng nhập quản lý</button></div>}
    <div className="catalog-controls">
      <div className="catalog-kind-tabs" role="group" aria-label="Chọn danh mục">{kinds.map(([kind,label])=><button type="button" className={tab===kind?'selected':''} key={kind} disabled={busy} onClick={()=>changeTab(kind)}>{label}</button>)}</div>
      <div className="catalog-toolbar"><label>Trạng thái <select aria-label="Trạng thái danh mục" value={state} disabled={busy} onChange={e=>{setState(e.target.value);setPage(1);setEditing(null);}}><option value="active">Đang sử dụng</option><option value="inactive">Ngừng sử dụng</option><option value="all">Tất cả</option></select></label><button className="btn" disabled={busy||loading} onClick={reload}>Làm mới</button><button className="btn primary" disabled={!canManage||busy||loading} onClick={newEntry}>Thêm {tabLabel.toLocaleLowerCase('vi')}</button></div>
    </div>
    {!confirmation&&!editing&&errorBox}
    {loading?<p className="catalog-state" role="status">Đang tải danh mục…</p>:error&&!editing?<p className="catalog-state">Chưa tải được danh sách. Hãy tải lại để tiếp tục.</p>:!entries.length?<p className="catalog-state">{demo?'Đăng nhập hệ thống để quản lý danh mục.':state==='inactive'?'Chưa có danh mục ngừng sử dụng.':'Chưa có danh mục trong danh sách này.'}</p>:<ul className="catalog-entries">{entries.map(item=><li key={item.id}>
      <div className="catalog-entry-title"><strong>{item.name||item.lot_code}</strong><span>{item.sku||item.code||item.product_type?.name}</span><small>{item.effective_active?'Đang sử dụng':item.is_active?'Tạm ẩn do loại sản phẩm ngừng sử dụng':'Ngừng sử dụng'} · {item.is_used?'Đã được dùng':'Chưa được dùng'}</small></div>
      <div className="catalog-entry-actions"><button className="btn" disabled={!canManage||busy} onClick={()=>{setEditing({...item,reason:''});setError('');}}>Sửa</button><button className="btn" disabled={!canManage||busy} onClick={()=>{setHistory(item);setHistoryPage(1);}}>Lịch sử</button>{!item.is_active?<button className="btn" disabled={!canManage||busy} onClick={()=>{setReason('');setError('');setConfirmation({item,restore:true});}}>Khôi phục</button>:<button className="btn catalog-danger" disabled={!canManage||busy} onClick={()=>{setReason('');setError('');setConfirmation({item,restore:false});}}>Xóa</button>}</div>
    </li>)}</ul>}
    <div className="catalog-pagination"><button className="btn" disabled={page===1||busy||loading} onClick={()=>setPage(page-1)}>Trang trước</button><span>Trang {page} · {total} mục</span><button className="btn" disabled={page*20>=total||busy||loading} onClick={()=>setPage(page+1)}>Trang sau</button></div>
    {editing&&<div className="modal-backdrop catalog-backdrop"><form role="dialog" aria-modal="true" className="modal compact-modal catalog-dialog catalog-edit" onSubmit={save} onKeyDown={event=>dialogKeys(event,()=>setEditing(null))} aria-label="Chỉnh sửa danh mục"><h3>{editing.id?'Sửa':'Thêm'} {tabLabel.toLocaleLowerCase('vi')}</h3>
      {errorBox}<fieldset disabled={busy}>
      {tab==='batches'?<><Field label="Loại sản phẩm *"><select autoFocus required value={editing.product_type_id} disabled={editing.is_used} onChange={e=>setEditing({...editing,product_type_id:e.target.value})}><option value="">Chọn loại sản phẩm</option>{products.filter(product=>product.is_active||product.id===editing.product_type_id).map(product=><option key={product.id} value={product.id}>{product.sku} · {product.name}{!product.is_active?' (ngừng sử dụng)':''}</option>)}</select></Field>{editing.is_used&&<p>Lô đã được dùng nên không thể chuyển sang loại sản phẩm khác.</p>}<Field label="Mã lô *"><input required maxLength={100} value={editing.lot_code} onChange={e=>setEditing({...editing,lot_code:e.target.value})}/></Field></>:<>
      <Field label={tab==='product-types'?'Mã SKU *':'Mã lỗi *'}><input autoFocus required maxLength={80} value={editing.sku??editing.code} onChange={e=>setEditing({...editing,[tab==='product-types'?'sku':'code']:e.target.value})}/></Field>
      <Field label="Tên danh mục *"><input required maxLength={tab==='product-types'?200:160} value={editing.name} onChange={e=>setEditing({...editing,name:e.target.value})}/></Field>
      {tab==='product-types'?<Field label="Đơn vị tính *"><input required maxLength={40} value={editing.unit_of_measure} onChange={e=>setEditing({...editing,unit_of_measure:e.target.value})}/></Field>:<Field label="Mức độ mặc định"><select value={editing.severity_default} onChange={e=>setEditing({...editing,severity_default:e.target.value})}>{Object.entries(severities).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></Field>}</>}
      {editing.id&&<Field label="Lý do sửa *"><textarea required minLength={3} maxLength={2000} value={editing.reason} onChange={e=>setEditing({...editing,reason:e.target.value})}/></Field>}
      <div className="catalog-form-actions"><button type="button" className="btn" onClick={()=>setEditing(null)}>Hủy sửa</button><button className="btn primary">{busy?'Đang lưu…':'Lưu danh mục'}</button></div>
      </fieldset>
    </form></div>}
    {confirmation&&<div className="modal-backdrop catalog-backdrop"><form role="dialog" aria-modal="true" aria-labelledby="catalog-confirm-title" className="modal compact-modal catalog-dialog" onSubmit={confirm} onKeyDown={event=>dialogKeys(event,()=>setConfirmation(null))}>
      <h3 id="catalog-confirm-title">{confirmation.restore?'Khôi phục danh mục?':confirmation.item.is_used?'Ngừng sử dụng danh mục?':'Xóa danh mục?'}</h3><p><strong>{confirmation.item.name||confirmation.item.lot_code}</strong></p><p>{confirmation.restore?'Mục này sẽ được dùng lại cho ghi nhận mới nếu loại sản phẩm cha đang hoạt động.':confirmation.item.is_used?'Danh mục đã được dùng nên chỉ ngừng sử dụng. Hồ sơ và báo cáo cũ được giữ nguyên.':'Danh mục hiện chưa được dùng. Máy chủ sẽ kiểm tra lại: chỉ xóa hẳn nếu vẫn chưa có dữ liệu liên quan.'}</p>
      <Field label="Lý do *"><textarea autoFocus required minLength={3} maxLength={2000} disabled={busy} value={reason} onChange={e=>setReason(e.target.value)}/></Field>{errorBox}<div className="catalog-form-actions"><button type="button" className="btn" disabled={busy} onClick={()=>setConfirmation(null)}>Hủy</button><button className="btn primary" disabled={busy}>{busy?'Đang xử lý…':confirmation.restore?'Xác nhận khôi phục':'Xác nhận xóa'}</button></div>
    </form></div>}
    {showLogin&&<div className="modal-backdrop catalog-backdrop"><form role="dialog" aria-modal="true" aria-labelledby="catalog-login-title" className="modal compact-modal catalog-dialog" onSubmit={login} onKeyDown={event=>dialogKeys(event,()=>setShowLogin(false))}>
      <h3 id="catalog-login-title">Đăng nhập quản lý danh mục</h3>{demoLogin?<><p>Bản test public: nhập mật khẩu bất kỳ là vào được.</p><input type="hidden" name="username" value="public.catalog"/></>:<Field label="Tên đăng nhập"><input autoFocus required name="username" autoComplete="username" disabled={busy}/></Field>}<Field label={demoLogin?"Mật khẩu bất kỳ":"Mật khẩu"}><input autoFocus={demoLogin} required type="password" name="password" autoComplete={demoLogin?"off":"current-password"} disabled={busy}/></Field>{loginError&&<p role="alert" className="catalog-error">{loginError}</p>}<div className="catalog-form-actions"><button className="btn" type="button" disabled={busy} onClick={()=>setShowLogin(false)}>Hủy</button><button className="btn primary" disabled={busy}>{busy?'Đang xác thực…':'Đăng nhập'}</button></div>
    </form></div>}
    {history&&<div className="modal-backdrop catalog-backdrop"><section role="dialog" aria-modal="true" aria-labelledby="catalog-history-title" className="modal catalog-dialog" onKeyDown={event=>dialogKeys(event,()=>setHistory(null))}><h3 id="catalog-history-title">Lịch sử: {history.name||history.lot_code}</h3><button className="btn" type="button" autoFocus onClick={()=>setHistory(null)}>Đóng lịch sử</button>
      {historyLoading?<p role="status">Đang tải lịch sử…</p>:historyError?<div className="catalog-error" role="alert">{historyError}<button className="btn" onClick={()=>setHistoryRevision(value=>value+1)}>Thử lại</button></div>:historyData.items.length?<ol className="catalog-history">{historyData.items.map((event:Row)=><li key={event.id}><strong>{actions[event.action]||event.action}</strong><p>{event.actor_name} · {formatTime(event.created_at)}</p>{event.reason&&<p>Lý do: {event.reason}</p>}<dl>{Object.entries(fields).filter(([field])=>event.changed_fields?.before?.[field]!==event.changed_fields?.after?.[field]).map(([field,label])=><div key={field}><dt>{label}</dt><dd>{historyValue(field,event.changed_fields?.before?.[field])} → {historyValue(field,event.changed_fields?.after?.[field])}</dd></div>)}</dl></li>)}</ol>:<p>Chưa có lịch sử thay đổi được ghi nhận.</p>}
      <div className="catalog-pagination"><button className="btn" disabled={historyLoading||historyPage===1} onClick={()=>setHistoryPage(historyPage-1)}>Trang trước</button><span>Trang {historyPage}</span><button className="btn" disabled={historyLoading||historyPage*20>=historyData.total} onClick={()=>setHistoryPage(historyPage+1)}>Trang sau</button></div>
    </section></div>}
  </section>;
}
