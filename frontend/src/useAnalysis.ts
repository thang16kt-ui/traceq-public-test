import {useEffect, useMemo, useState} from 'react';
import {api, errorMessage, rows} from './api';
import type {Row} from './api';
import {demoSummary,demoPareto,demoTrends} from './demo';

export function useAnalysis(user:Row|null,demo:boolean,period:string,productId:string,batchId:string,revision:number){
  const query=useMemo(()=>{
    const params=new URLSearchParams();
    if(period!=='all'){
      const end=new Date(),start=new Date(end);
      start.setDate(start.getDate()-(period==='week'?7:30));
      params.set('period_start',start.toISOString());params.set('period_end',end.toISOString());
    }
    if(productId)params.set('product_type_id',productId);
    if(batchId)params.set('batch_id',batchId);
    return params.toString();
  },[period,productId,batchId,revision]);
  const enabled=!!user&&user.role!=='inspector'&&!demo;
  const key=JSON.stringify([user?.id,query,revision]);
  const [state,setState]=useState<{key:string;data:Row|null;error:string}>({key:'',data:null,error:''});
  useEffect(()=>{
    if(!enabled)return;
    const controller=new AbortController();let active=true;
    setState({key,data:null,error:''});
    Promise.all(['summary','pareto','trends','forecast'].map(path=>api(`/analytics/${path}${query?'?'+query:''}`,{signal:controller.signal})))
      .then(([summary,pareto,trends,forecast])=>{if(active)setState({key,data:{summary,pareto:rows(pareto),trends:rows(trends),forecast},error:''});})
      .catch(error=>{if(active)setState({key,data:null,error:errorMessage(error)});});
    return()=>{active=false;controller.abort();};
  },[enabled,key,query]);
  const current=state.key===key?state:null;
  const data=demo?{summary:demoSummary,pareto:demoPareto,trends:demoTrends,forecast:{available:false,message:'Chưa đủ dữ liệu để dự báo',reasons:['Dữ liệu minh họa chưa đủ để dự báo.']}}:current?.data;
  return {summary:(data?.summary||{}) as Row,pareto:(data?.pareto||[]) as Row[],trends:(data?.trends||[]) as Row[],forecast:(data?.forecast||{}) as Row,
    loading:enabled&&(!current||(!current.data&&!current.error)),error:enabled?current?.error||'':'',query};
}
