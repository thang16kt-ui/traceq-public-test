import {Component} from 'react';
import type {ErrorInfo, ReactNode} from 'react';
import {reportError} from './lib/errors';

export function reloadApp(){
  const url=new URL(location.href);
  url.searchParams.set('reload',String(Date.now()));
  location.replace(url.toString());
}

export default class AppErrorBoundary extends Component<{children:ReactNode},{error:string|null}>{
  state:{error:string|null}={error:null};
  static getDerivedStateFromError(error:unknown){
    return {error:error instanceof Error?error.message:String(error)};
  }
  componentDidCatch(error:unknown,info:ErrorInfo){
    reportError('Trang trắng: '+(error instanceof Error?error.message:String(error)),(error instanceof Error?error.stack||'':'')+'\n'+(info.componentStack||''));
  }
  render(){
    if(this.state.error!==null)return <main className="app-recovery" role="alert">
      <h1>Chưa mở được TraceQ</h1>
      <p>Giao diện gặp lỗi. Bạn có thể tải lại để thử mở bản mới nhất.</p>
      <p>Dữ liệu đã gửi lên hệ thống không bị xóa.</p>
      <button type="button" onClick={reloadApp}>Tải lại TraceQ</button>
      <details><summary>Thông tin lỗi để gửi hỗ trợ</summary><p>{this.state.error.slice(0,500)}</p></details>
    </main>;
    return this.props.children;
  }
}
