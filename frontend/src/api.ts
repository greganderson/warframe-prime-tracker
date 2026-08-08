export async function api<T>(path:string, init?:RequestInit):Promise<T>{
  const response=await fetch(`/api/v1${path}`,{...init,headers:{'Content-Type':'application/json',...(init?.headers||{})}});
  if(!response.ok){let message=`Request failed (${response.status})`;try{message=(await response.json()).detail||message}catch{}throw new Error(message)}
  return response.json();
}
export const patch=(path:string,body:unknown)=>api(path,{method:'PATCH',body:JSON.stringify(body)});
export const post=<T>(path:string,body?:unknown)=>api<T>(path,{method:'POST',body:body===undefined?undefined:JSON.stringify(body)});
