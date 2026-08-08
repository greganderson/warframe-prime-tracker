import {useEffect,useMemo,useState} from 'react';
import {api,patch} from './api';
import type {Equipment} from './types';

export function Manage(){
 const [equipment,setEquipment]=useState<Equipment[]>([]),[query,setQuery]=useState(''),[error,setError]=useState('');
 const load=()=>api<Equipment[]>('/collection').then(setEquipment).catch(e=>setError(e.message));
 useEffect(()=>{void load()},[]);
 const filtered=useMemo(()=>equipment.filter(e=>`${e.name} ${e.parts.map(p=>p.name).join(' ')}`.toLowerCase().includes(query.toLowerCase())),[equipment,query]);
 async function qty(id:string,delta:number){try{await patch(`/inventory/${id}`,{delta});load()}catch(e){setError((e as Error).message)}}
 async function toggle(id:string,key:'owned'|'mastered'|'favorite'|'target',value:number){await patch(`/equipment/${id}`,{[key]:!value});load()}
 async function upload(path:string,file:File){const body=new FormData();body.append('file',file);const r=await fetch(`/api/v1${path}`,{method:'POST',body});if(!r.ok)setError((await r.json()).detail);else load()}
 return <main className="manage">
   <header><div><span className="eyebrow">ORBITER ARCHIVE</span><h1>Prime Collection</h1></div><a className="run-link" href="/display">Open Run Mode →</a></header>
   {error&&<div className="error" onClick={()=>setError('')}>{error} ×</div>}
   <section className="toolbar"><input autoFocus placeholder="Search equipment or parts…" value={query} onChange={e=>setQuery(e.target.value)}/><a href="/api/v1/inventory.csv" download>Export CSV</a><a href="/api/v1/backup" download>JSON backup</a><label>Import CSV<input hidden type="file" accept=".csv" onChange={e=>e.target.files?.[0]&&upload('/inventory/import',e.target.files[0])}/></label><label>Restore<input hidden type="file" accept=".json" onChange={e=>e.target.files?.[0]&&upload('/backup/restore',e.target.files[0])}/></label></section>
   <section className="summary"><article><b>{equipment.filter(e=>e.ready).length}</b><span>Ready to build</span></article><article><b>{equipment.filter(e=>e.mastered).length}</b><span>Mastered</span></article><article><b>{equipment.reduce((n,e)=>n+e.missing_count,0)}</b><span>Parts missing</span></article></section>
   <div className="cards">{filtered.map(e=><article className="equipment" key={e.id}>
    <div className="equipment-title"><div><span className={`status ${e.availability}`}>{e.availability}</span><h2>{e.name}</h2><small>{e.ready?'SET COMPLETE':`${e.missing_count} REQUIRED`} · {e.surplus_sets} complete set{e.surplus_sets===1?'':'s'}</small></div><div className="checks">{(['target','favorite','owned','mastered'] as const).map(k=><button className={e[k]?'on':''} onClick={()=>toggle(e.id,k,e[k])} key={k}>{k}</button>)}</div></div>
    <div className="parts">{e.parts.map(p=><div className="part" key={p.id}><div><b>{p.name.replace(e.name,'').trim()||'Blueprint'}</b><span className={`rarity ${p.availability}`}>{p.availability}</span></div><div className="value"><span>{p.ducats} ◈</span><span>{p.market_median==null?'—':`${p.market_median}p`}</span></div><div className="stepper"><button aria-label={`Remove ${p.name}`} onClick={()=>qty(p.id,-1)}>−</button><strong>{p.owned}<i>/{p.required}</i></strong><button aria-label={`Add ${p.name}`} onClick={()=>qty(p.id,1)}>+</button></div></div>)}</div>
   </article>)}</div>
 </main>
}
