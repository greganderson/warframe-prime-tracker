import {useEffect,useMemo,useRef,useState} from 'react';
import {api,post} from './api';
import type {Relic,Reward,RunSession} from './types';

const eras=['Lith','Meso','Neo','Axi'];
type Picker={slot:number;era:string|null;letter:string|null}|null;

export function Display(){
 const [relics,setRelics]=useState<Relic[]>([]),[slots,setSlots]=useState<(string|null)[]>([null,null,null,null]);
 const [picker,setPicker]=useState<Picker>(null),[loadingCatalog,setLoadingCatalog]=useState(false);
 const [run,setRun]=useState<RunSession|null>(null),[loadingPrices,setLoadingPrices]=useState(false),[chosen,setChosen]=useState<Reward|null>(null),[tx,setTx]=useState<string|null>(null),[error,setError]=useState('');
 const lock=useRef(false);

 useEffect(()=>{void loadCatalog()},[]);
 async function loadCatalog(){
  try{
   const current=await api<Relic[]>('/catalog/relics'); setRelics(current);
   if(current.length<100){
    setLoadingCatalog(true);
    await post('/catalog/relics/refresh');
    setRelics(await api<Relic[]>('/catalog/relics'));
   }
  }catch(e){setError((e as Error).message)}finally{setLoadingCatalog(false)}
 }
 const selectedRelics=slots.map(id=>relics.find(r=>r.id===id));
 const pickerRelics=picker?.era?relics.filter(r=>r.era===picker.era):[];
 const letters=useMemo(()=>[...new Set(pickerRelics.map(r=>r.code.match(/^[A-Z]+/)?.[0]).filter(Boolean) as string[])].sort(),[pickerRelics]);
 const numbered=picker?.letter?pickerRelics.filter(r=>r.code.startsWith(picker.letter!)).sort((a,b)=>Number(a.code.slice(picker.letter!.length))-Number(b.code.slice(picker.letter!.length))):[];

 function chooseRelic(id:string){if(!picker)return;setSlots(current=>current.map((value,index)=>index===picker.slot?id:value));setPicker(null)}
 async function updatePrices(current:RunSession){setLoadingPrices(true);try{const item_ids=[...new Set(current.columns.flatMap(column=>column.rewards.map(reward=>reward.id)))];await post('/market/prices',{item_ids});setRun(await api<RunSession>(`/runs/${current.id}`))}catch(e){setError((e as Error).message)}finally{setLoadingPrices(false)}}
 async function begin(){const ids=slots.filter(Boolean) as string[];if(!ids.length)return;try{const current=await post<RunSession>('/runs',{relic_ids:ids});setRun(current);setChosen(null);setTx(null);void updatePrices(current)}catch(e){setError((e as Error).message)}}
 async function confirm(){if(!run||!chosen||lock.current)return;lock.current=true;try{const result=await post<{transaction_id:string}>(`/runs/${run.id}/confirm`,{item_id:chosen.id,idempotency_key:`${run.id}-${chosen.id}`});setTx(result.transaction_id);setRun({...run,state:'confirmed',chosen_item_id:chosen.id})}catch(e){setError((e as Error).message)}finally{lock.current=false}}
 async function undo(){if(!tx)return;await post(`/transactions/${tx}/undo`);setRun(run?{...run,state:'open',chosen_item_id:null}:null);setChosen(null);setTx(null)}

 if(!run)return <main className="display picker">
  <header><div><span className="eyebrow">VOID FISSURE</span><h1>Squad Relics</h1></div><span>{loadingCatalog?'Updating relic catalog…':`${relics.length} relics available`}</span><a href="/manage">Manage</a></header>
  {error&&<div className="error" onClick={()=>setError('')}>{error} ×</div>}
  <div className="chosen-slots">{slots.map((id,i)=>{const relic=selectedRelics[i];return <button className={`${relic?'filled':''} ${relic?.availability==='vaulted'?'is-vaulted':''}`} onClick={()=>setPicker({slot:i,era:relic?.era??null,letter:null})} key={i}><small>SQUAD {i+1}</small>{relic?<><b>{relic.era}</b><strong>{relic.code}</strong><em>{relic.availability}</em></>:<span>Tap to choose</span>}</button>})}</div>
  <div className="picker-hint">Tap a squad slot, then choose era → letter → number.</div>
  <button className="begin" disabled={!slots.some(Boolean)} onClick={begin}>Show Rewards</button>
  {picker&&<div className="relic-picker-modal">
   <div className="modal-head"><button onClick={()=>picker.letter?setPicker({...picker,letter:null}):picker.era?setPicker({...picker,era:null}):setPicker(null)}>← Back</button><div><span className="eyebrow">SQUAD {picker.slot+1}</span><h2>{picker.letter?`${picker.era} ${picker.letter}…`:picker.era?`${picker.era}: choose letter`:'Choose era'}</h2></div><button onClick={()=>{setSlots(s=>s.map((v,i)=>i===picker.slot?null:v));setPicker(null)}}>Clear</button></div>
   {!picker.era&&<div className="touch-options eras">{eras.map(era=><button disabled={!relics.some(r=>r.era===era)} onClick={()=>setPicker({...picker,era})} key={era}>{era}<small>{relics.filter(r=>r.era===era).length} relics</small></button>)}</div>}
   {picker.era&&!picker.letter&&<div className="touch-options letters">{letters.map(letter=><button onClick={()=>setPicker({...picker,letter})} key={letter}>{letter}<small>{pickerRelics.filter(r=>r.code.startsWith(letter)).length}</small></button>)}</div>}
   {picker.letter&&<div className="touch-options numbers">{numbered.map(relic=><button className={relic.availability==='vaulted'?'is-vaulted':''} onClick={()=>chooseRelic(relic.id)} key={relic.id}><small>{relic.era} {picker.letter}</small>{relic.code.slice(picker.letter!.length)}<em>{relic.availability}</em></button>)}</div>}
  </div>}
 </main>;

 return <main className="display rewards"><header><button onClick={()=>setRun(null)}>← Relics</button><div><span className="eyebrow">SELECTED IN GAME</span><h1>Choose reward to record</h1></div><span className="round-state">{loadingPrices?'Loading prices…':run.state}</span></header><div className="reward-grid">{run.columns.map((col,i)=><section key={`${col.id}-${i}`}><h2>{col.era} {col.code}<small>SQUAD {i+1}</small><span className={`relic-status ${col.availability}`}>{col.availability}</span></h2>{col.rewards.map(r=><button disabled={run.state==='confirmed'} className={`reward ${r.rarity} ${r.mastered?'is-mastered':''} ${chosen?.id===r.id?'chosen':''}`} key={r.id} onClick={()=>setChosen(r)}><span className="reward-name">{r.name}{r.mastered&&<strong className="mastered-badge">MASTERED</strong>}</span><span className="reward-stats"><b>{r.owned}/{r.required||'✓'}</b><i>{r.rarity}</i><i>{r.ducats}◈</i><strong className="market-price">{loadingPrices?'…':r.market_median==null?'NO PRICE':`${r.market_median} PLAT`}</strong></span></button>)}</section>)}</div>{chosen&&run.state==='open'&&<button className="confirm" onClick={confirm}>Confirm {chosen.name} <span>+1 part</span></button>}{run.state==='confirmed'&&<div className="confirmed">Reward recorded <button onClick={undo}>Undo</button><button onClick={()=>setRun(null)}>Next round</button></div>}</main>
}
